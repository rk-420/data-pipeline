-- Creates a database in the AWS Glue Data Catalog (free for the first million objects).
-- Run in the Athena query editor, workgroup "energy".
CREATE DATABASE IF NOT EXISTS energy
COMMENT 'German electricity market data from SMARD';
