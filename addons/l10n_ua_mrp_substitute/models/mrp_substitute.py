"""Погоджені аналоги компонентів і заміна відсутніх компонентів у виробничому замовленні.

Аналог належить рядку специфікації: виріб, коефіцієнт, пріоритет. Коефіцієнт - скільки аналога
(в його одиниці) йде замість однієї одиниці компонента (в одиниці компонента). Без погодження
аналог не використовується; погоджує керівник виробництва з підставою, і будь-яка зміна виробу
чи коефіцієнта погодження знімає.

Заміна в замовленні: нестача компонента = потреба мінус зарезервоване. Її покриває вільний
залишок аналогів у місці списання замовлення, від найвищого пріоритету. Потреба в основному
компоненті зменшується на покрите, аналог додається окремим рядком з позначкою «замість».
"""
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round


class UaBomSubstitute(models.Model):
    _name = "ua.bom.substitute"
    _description = "Аналог компонента в специфікації"
    _order = "bom_line_id, sequence, id"

    bom_line_id = fields.Many2one("mrp.bom.line", "Рядок специфікації", required=True, index=True,
                                  ondelete="cascade")
    bom_id = fields.Many2one(related="bom_line_id.bom_id", store=True, string="Специфікація")
    company_id = fields.Many2one(related="bom_line_id.bom_id.company_id", store=True)
    component_id = fields.Many2one(related="bom_line_id.product_id", store=True, string="Компонент")
    sequence = fields.Integer("Пріоритет", default=10)
    product_id = fields.Many2one("product.product", "Аналог", required=True,
                                 domain="[('type', '=', 'consu')]")
    factor = fields.Float("Коефіцієнт", default=1.0, required=True, digits="Product Unit",
                          help="Скільки аналога (в його одиниці) замість однієї одиниці компонента.")
    approval_ref = fields.Char("Підстава", help="Повідомлення про зміну, протокол, рішення представника "
                                                "замовника - документ, яким заміну дозволено.")
    approved_by = fields.Many2one("res.users", "Погодив", readonly=True, copy=False)
    approved_on = fields.Date("Дата погодження", readonly=True, copy=False)
    approved = fields.Boolean("Погоджено", compute="_compute_approved", store=True)
    note = fields.Char("Примітка")

    @api.depends("approved_by")
    def _compute_approved(self):
        for row in self:
            row.approved = bool(row.approved_by)

    @api.constrains("product_id", "factor", "bom_line_id")
    def _check_row(self):
        for row in self:
            if row.factor <= 0:
                raise ValidationError(_("Коефіцієнт аналога має бути більший за нуль."))
            if row.product_id == row.bom_line_id.product_id:
                raise ValidationError(_("Аналог не може бути тим самим виробом, що й компонент."))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("ua_substitute_approval"):
            vals_list = [{k: v for k, v in vals.items() if k not in ("approved_by", "approved_on")}
                         for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        if {"approved_by", "approved_on"} & set(vals) and not self.env.context.get("ua_substitute_approval"):
            raise UserError(_("Погодження ставиться лише кнопкою «Погодити»."))
        if {"product_id", "factor", "bom_line_id"} & set(vals):
            vals = dict(vals, approved_by=False, approved_on=False)
            return super(UaBomSubstitute, self.with_context(ua_substitute_approval=True)).write(vals)
        return super().write(vals)

    def action_approve(self):
        if not self.env.user.has_group("mrp.group_mrp_manager"):
            raise UserError(_("Погоджує аналог керівник виробництва."))
        for row in self:
            if not (row.approval_ref or "").strip():
                raise UserError(_("Вкажіть підставу заміни: %s замість %s.")
                                % (row.product_id.display_name, row.component_id.display_name))
        self.with_context(ua_substitute_approval=True).write({
            "approved_by": self.env.user.id, "approved_on": fields.Date.context_today(self)})
        return True

    def action_revoke(self):
        if not self.env.user.has_group("mrp.group_mrp_manager"):
            raise UserError(_("Знімає погодження керівник виробництва."))
        self.with_context(ua_substitute_approval=True).write({"approved_by": False, "approved_on": False})
        return True


class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    ua_substitute_ids = fields.One2many("ua.bom.substitute", "bom_line_id", "Аналоги", copy=True)


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    ua_substitute_count = fields.Integer("Аналоги", compute="_compute_ua_substitute_count")

    def _compute_ua_substitute_count(self):
        counts = dict(self.env["ua.bom.substitute"]._read_group(
            [("bom_id", "in", self.ids)], ["bom_id"], ["__count"]))
        for bom in self:
            bom.ua_substitute_count = counts.get(bom, 0)

    def action_ua_substitutes(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("l10n_ua_mrp_substitute.action_ua_bom_substitute")
        action["domain"] = [("bom_id", "=", self.id)]
        action["context"] = {"search_default_bom_id": self.id}
        return action


class StockMove(models.Model):
    _inherit = "stock.move"

    ua_substitute_id = fields.Many2one("ua.bom.substitute", "Погоджений аналог", readonly=True,
                                       copy=False, index="btree_not_null")
    ua_substitute_of_id = fields.Many2one("product.product", "Замість", readonly=True, copy=False)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def _ua_shortage(self, move):
        """Нестача рядка в одиниці виробу компонента."""
        missing = move.product_uom_qty - move.quantity
        if move.product_uom.compare(missing, 0.0) <= 0:
            return 0.0
        return move.product_uom._compute_quantity(missing, move.product_id.uom_id)

    def action_ua_substitute(self):
        """Покрити нестачу компонентів вільним залишком погоджених аналогів."""
        done = []
        for production in self:
            if production.state not in ("confirmed", "progress", "to_close"):
                raise UserError(_("%s: замінювати компоненти можна в підтвердженому замовленні, "
                                  "ще не завершеному.") % production.name)
            production.move_raw_ids.filtered(
                lambda m: m.state in ("confirmed", "partially_available"))._action_assign()
            location = production.location_src_id
            for move in production.move_raw_ids.filtered(
                    lambda m: m.state not in ("done", "cancel") and not m.ua_substitute_id
                    and m.bom_line_id.ua_substitute_ids):
                missing = production._ua_shortage(move)
                if not missing:
                    continue
                component = move.product_id
                for row in move.bom_line_id.ua_substitute_ids.filtered("approved").sorted(
                        lambda r: (r.sequence, r.id)):
                    substitute = row.product_id
                    free = substitute.with_context(location=location.id).free_qty
                    take = float_round(min(missing * row.factor, free),
                                       precision_rounding=substitute.uom_id.rounding,
                                       rounding_method="DOWN")
                    if take <= 0:
                        continue
                    covered = component.uom_id.round(take / row.factor)
                    covered_move_uom = component.uom_id._compute_quantity(covered, move.product_uom)
                    left = move.product_uom.round(move.product_uom_qty - covered_move_uom)
                    values = production._get_move_raw_values(
                        substitute, take, substitute.uom_id, operation_id=move.operation_id.id,
                        bom_line=move.bom_line_id)
                    values.update({"ua_substitute_id": row.id, "ua_substitute_of_id": component.id})
                    production.write({"move_raw_ids": [(0, 0, values)]})
                    if move.product_uom.compare(left, 0.0) <= 0 and move.product_uom.is_zero(move.quantity):
                        move._action_cancel()
                    else:
                        move.product_uom_qty = left
                    done.append((production, component, covered, substitute, take, row))
                    missing = component.uom_id.round(missing - covered)
                    if component.uom_id.compare(missing, 0.0) <= 0:
                        break
            production.move_raw_ids.filtered(
                lambda m: m.ua_substitute_id and m.state in ("confirmed", "partially_available"))._action_assign()
        if not done:
            raise UserError(_("Замінювати нічого: компонентів вистачає, або погоджених аналогів "
                              "немає на складі."))
        by_production = defaultdict(list)
        for production, component, covered, substitute, take, row in done:
            by_production[production].append(_(
                "%(sub)s, %(take)s %(sub_uom)s замість %(comp)s, %(covered)s %(comp_uom)s (підстава: %(ref)s)",
                sub=substitute.display_name, take=take, sub_uom=substitute.uom_id.name,
                comp=component.display_name, covered=covered, comp_uom=component.uom_id.name,
                ref=row.approval_ref or "-"))
        for production, rows in by_production.items():
            production.message_post(body=_("Заміна компонентів погодженими аналогами: %s.") % "; ".join(rows))
        return True

    def _get_consumption_issues(self):
        """Погоджена заміна - це споживання основного компонента, а не відхилення."""
        issues = super()._get_consumption_issues()
        if not issues:
            return issues
        credit, extra = defaultdict(float), set()
        for production in self:
            for move in production.move_raw_ids.filtered(lambda m: m.ua_substitute_id and m.picked):
                qty = move.product_uom._compute_quantity(move._get_picked_quantity(), move.product_id.uom_id)
                credit[(production, move.ua_substitute_of_id)] += qty / move.ua_substitute_id.factor
                extra.add((production, move.product_id))
        result = []
        for production, product, consumed, expected in issues:
            if (production, product) in extra and not expected:
                continue
            key = (production, product)
            if key in credit:
                consumed = product.uom_id.round(consumed + credit[key])
                if product.uom_id.compare(consumed, expected) == 0:
                    continue
            result.append((production, product, consumed, expected))
        return result
