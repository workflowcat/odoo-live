-- Bank API tokens and certificates stay with the source database; connections are switched off.
UPDATE online_bank_statement_provider
   SET active = false,
       username = NULL,
       password = NULL,
       certificate_public_key = NULL,
       certificate_private_key = NULL,
       certificate_chain = NULL;
DELETE FROM ir_attachment
 WHERE res_model = 'online.bank.statement.provider'
   AND res_field = 'certificate';
