-- A neutralised copy (`odoo neutralize`) must not reach the bridge with the source database's
-- token. bp.bridge also refuses calls on a neutralised database unless BP_BRIDGE_ON_NEUTRALIZED=1.
DELETE FROM ir_config_parameter
 WHERE key IN ('bp_bridge.url', 'bp_bridge.token', 'bp_kyc.bridge_url', 'bp_kyc.bridge_token');
