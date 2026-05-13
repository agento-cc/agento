import nodemailer from 'nodemailer';

export function createTransporter(opts) {
  return nodemailer.createTransport(opts);
}
