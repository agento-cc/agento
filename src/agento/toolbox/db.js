import mysql from 'mysql2/promise';

let pool = null;

export function getCronPool() {
  if (!pool) {
    pool = mysql.createPool({
      host:     process.env.CRONDB_HOST || 'mysql',
      port:     parseInt(process.env.CRONDB_PORT || '3306'),
      user:     process.env.CRONDB_USER || 'cron_agent',
      password: process.env.CRONDB_PASSWORD,
      database: process.env.CRONDB_DATABASE || 'cron_agent',
      waitForConnections: true,
      connectionLimit: 2,
    });
  }
  return pool;
}
