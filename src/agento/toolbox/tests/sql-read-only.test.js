import { describe, expect, it } from 'vitest';
import { isReadOnlySql } from '../adapters/sql-read-only.js';

const MYSQL_STARTS = ['SELECT', 'SHOW', 'DESCRIBE', 'EXPLAIN', 'WITH'];
const MSSQL_STARTS = ['SELECT', 'WITH'];

describe('SQL read-only validation', () => {
  it.each([
    'SELECT * FROM report',
    'SELECT * FROM report;',
    "SELECT 'DELETE FROM report; -- text only' AS sample",
    '/* report */ WITH rows AS (SELECT 1 AS id) SELECT * FROM rows',
  ])('allows one read-only statement: %s', query => {
    expect(isReadOnlySql(query, MSSQL_STARTS, { dialect: 'mssql' })).toBe(true);
  });

  it.each([
    'WITH rows AS (SELECT 1 AS id) DELETE FROM report',
    'SELECT 1; DELETE FROM report',
    'SELECT * INTO report_copy FROM report',
    'SELECT 1; -- trailing comment\nDELETE FROM report',
    'SELECT * FROM #temp; DELETE FROM report',
    "SELECT '\\'; DELETE FROM report --'",
    "SELECT * FROM OPENQUERY([linked], 'DELETE FROM report RETURNING *')",
    'EXEC sp_help',
    '/* unterminated',
  ])('blocks a write or batch bypass: %s', query => {
    expect(isReadOnlySql(query, MSSQL_STARTS, { dialect: 'mssql' })).toBe(false);
  });

  it('keeps MySQL metadata statements while blocking mutating CTEs', () => {
    const options = { dialect: 'mysql' };
    expect(isReadOnlySql('SHOW TABLES', MYSQL_STARTS, options)).toBe(true);
    expect(isReadOnlySql('SHOW CREATE TABLE report', MYSQL_STARTS, options)).toBe(true);
    expect(isReadOnlySql('DESCRIBE report', MYSQL_STARTS, options)).toBe(true);
    expect(isReadOnlySql('WITH rows AS (SELECT 1) UPDATE report SET value = 1', MYSQL_STARTS, options)).toBe(false);
    expect(isReadOnlySql('SELECT 1 # comment', MYSQL_STARTS, options)).toBe(true);
    expect(isReadOnlySql('SELECT 1-- comment', MYSQL_STARTS, options)).toBe(true);
    expect(isReadOnlySql("SELECT 1--@x INTO OUTFILE '/tmp/x'", MYSQL_STARTS, options)).toBe(false);
    expect(isReadOnlySql('SELECT 1 /*!50000; DELETE FROM report */', MYSQL_STARTS, options)).toBe(false);
    expect(isReadOnlySql('SELECT 1 /* outer /* inner */; DELETE FROM report */', MYSQL_STARTS, options)).toBe(false);
  });

  it('fails closed for PostgreSQL escape-string ambiguity', () => {
    const query = "SELECT E'foo\\'bar'; DELETE FROM report --'";
    expect(isReadOnlySql(query, ['SELECT', 'WITH'], { dialect: 'postgresql' })).toBe(false);
  });
});
