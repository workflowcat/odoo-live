-- Odoo switches incoming mail servers off; their passwords go too, so a copy carries no mailbox login.
UPDATE fetchmail_server
   SET password = NULL;
