#!/usr/bin/env node
'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');

function loadLocalEnv(filePath) {
  try {
    if (!filePath || !fs.existsSync(filePath)) return;
    const raw = fs.readFileSync(filePath, 'utf8');
    raw.split(/\r?\n/).forEach(line => {
      const trimmed = String(line || '').trim();
      if (!trimmed || trimmed.startsWith('#')) return;
      const match = trimmed.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
      if (!match) return;
      const key = match[1];
      let value = match[2].trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      value = value.replace(/\\n/g, '\n');
      if (process.env[key] === undefined || process.env[key] === '') {
        process.env[key] = value;
      }
    });
  } catch (_) {
    // Ignore env file parse errors; process env remains primary source of truth.
  }
}

const PROJECT_ROOT = path.resolve(__dirname, '..');
const DEFAULT_DATA_FILE = path.join(PROJECT_ROOT, 'data', 'reminder-store.json');
const LOCAL_ENV_FILE = process.env.SP_ENV_FILE || path.join(PROJECT_ROOT, '.env.local');
loadLocalEnv(LOCAL_ENV_FILE);

const PORT = Number(process.env.SP_REMINDER_PORT || 8787);
const HOST = process.env.SP_REMINDER_HOST || '127.0.0.1';
const API_KEY = process.env.SP_REMINDER_API_KEY || '';
const DATA_FILE = process.env.SP_REMINDER_DATA_FILE || DEFAULT_DATA_FILE;
const CHECK_INTERVAL_MINUTES = Number(process.env.SP_REMINDER_INTERVAL_MINUTES || 30);
const OVERDUE_GRACE_DAYS = Number(process.env.SP_REMINDER_OVERDUE_GRACE_DAYS || 2);

const TWILIO_ACCOUNT_SID = process.env.TWILIO_ACCOUNT_SID || '';
const TWILIO_AUTH_TOKEN = process.env.TWILIO_AUTH_TOKEN || '';
const TWILIO_SMS_FROM = process.env.TWILIO_SMS_FROM || '';
const TWILIO_WHATSAPP_FROM = process.env.TWILIO_WHATSAPP_FROM || '';
const RESEND_API_KEY = process.env.RESEND_API_KEY || '';
const EMAIL_FROM = process.env.EMAIL_FROM || '';
const SENDGRID_API_KEY = process.env.SENDGRID_API_KEY || '';

const STATE_MAX_LOGS = 5000;
const MAX_BODY_BYTES = 2 * 1024 * 1024;

function getEmailFromAddress() {
  return EMAIL_FROM || (RESEND_API_KEY ? 'Skim Pintar <onboarding@resend.dev>' : '');
}

function hasEmailProviderConfigured() {
  return Boolean((RESEND_API_KEY || SENDGRID_API_KEY) && getEmailFromAddress());
}

function getEmailProvider() {
  if (RESEND_API_KEY) return 'resend';
  if (SENDGRID_API_KEY) return 'sendgrid';
  return '';
}

function defaultStore() {
  return {
    donors: [],
    sentCycles: {},
    sentEvents: {},
    deliveryLog: [],
    lastSyncAt: null,
    updatedAt: null
  };
}

function ensureDataFile() {
  const dir = path.dirname(DATA_FILE);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  if (!fs.existsSync(DATA_FILE)) {
    fs.writeFileSync(DATA_FILE, JSON.stringify(defaultStore(), null, 2), 'utf8');
  }
}

function readStore() {
  ensureDataFile();
  try {
    const raw = fs.readFileSync(DATA_FILE, 'utf8');
    const parsed = JSON.parse(raw);
    return {
      ...defaultStore(),
      ...(parsed && typeof parsed === 'object' ? parsed : {})
    };
  } catch (_) {
    return defaultStore();
  }
}

function writeStore(store) {
  const next = {
    ...defaultStore(),
    ...(store && typeof store === 'object' ? store : {})
  };
  next.updatedAt = new Date().toISOString();
  fs.writeFileSync(DATA_FILE, JSON.stringify(next, null, 2), 'utf8');
}

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(body);
}

function setCors(res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type,x-sp-api-key');
}

function isAuthorized(req) {
  if (!API_KEY) return true;
  return String(req.headers['x-sp-api-key'] || '') === API_KEY;
}

function parseJsonBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', chunk => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(new Error('Request body too large.'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      try {
        const raw = Buffer.concat(chunks).toString('utf8').trim();
        resolve(raw ? JSON.parse(raw) : {});
      } catch (err) {
        reject(new Error(`Invalid JSON body: ${err.message}`));
      }
    });
    req.on('error', reject);
  });
}

function normalizeEmail(value) {
  return String(value || '').trim().toLowerCase();
}

function normalizeNric(value) {
  return String(value || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}

function normalizeNotifyChannel(value) {
  const channel = String(value || '').trim().toLowerCase();
  return ['whatsapp', 'sms', 'email'].includes(channel) ? channel : 'whatsapp';
}

function toSgE164(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  if (/^\+\d{8,15}$/.test(raw)) return raw;
  const digits = raw.replace(/\D/g, '');
  if (!digits) return '';
  if (digits.startsWith('65') && digits.length >= 10 && digits.length <= 15) return `+${digits}`;
  if (digits.length === 8) return `+65${digits}`;
  if (digits.length >= 8 && digits.length <= 15) return `+${digits}`;
  return '';
}

function monthKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function getDueDateForCurrentMonth(record, now = new Date()) {
  const day = Number(record?.donor?.egiroDeductionDay || 0);
  if (!Number.isFinite(day) || day < 1) return null;
  const year = now.getFullYear();
  const month = now.getMonth();
  const lastDay = new Date(year, month + 1, 0).getDate();
  const validDay = Math.min(Math.max(day, 1), lastDay);
  return new Date(year, month, validDay, 0, 0, 0, 0);
}

function isOverdue(record, now = new Date()) {
  if (!record || record.terminatedAt) return { overdue: false, dueDate: null, reason: 'terminated' };
  const dueDate = getDueDateForCurrentMonth(record, now);
  if (!dueDate) return { overdue: false, dueDate: null, reason: 'missing_due_day' };
  const graceEnd = new Date(dueDate.getTime());
  graceEnd.setDate(graceEnd.getDate() + OVERDUE_GRACE_DAYS);
  if (now <= graceEnd) return { overdue: false, dueDate, reason: 'within_grace' };
  return { overdue: true, dueDate, reason: 'overdue' };
}

function sanitizeDonorRecord(input) {
  if (!input || typeof input !== 'object') return null;
  const donor = input.donor && typeof input.donor === 'object' ? input.donor : null;
  if (!donor) return null;
  const applicationId = String(input.applicationId || '').trim();
  const nric = normalizeNric(donor.nric || donor.nricNormalized || '');
  if (!applicationId || !nric) return null;

  return {
    applicationId,
    submittedAt: input.submittedAt || new Date().toISOString(),
    updatedAt: input.updatedAt || null,
    terminatedAt: input.terminatedAt || null,
    donor: {
      fullName: String(donor.fullName || '').trim(),
      nric,
      mobile: String(donor.mobile || '').trim(),
      email: normalizeEmail(donor.email || ''),
      address: String(donor.address || '').trim(),
      contribution: Number(donor.contribution || 0),
      group: String(donor.group || '').trim(),
      notifyChannel: normalizeNotifyChannel(donor.notifyChannel || ''),
      egiroBank: String(donor.egiroBank || '').trim(),
      egiroAccount: String(donor.egiroAccount || '').trim(),
      egiroAccountHolder: String(donor.egiroAccountHolder || '').trim(),
      egiroDeductionDay: String(donor.egiroDeductionDay || '').trim(),
      egiroStartMonth: String(donor.egiroStartMonth || '').trim(),
      authUserId: String(donor.authUserId || '').trim(),
      authUserEmail: normalizeEmail(donor.authUserEmail || '')
    },
    relatives: Array.isArray(input.relatives) ? input.relatives : []
  };
}

function formatMoney(value) {
  const amount = Number(value || 0);
  return Number.isFinite(amount) ? `$${amount.toFixed(2)}` : '$0.00';
}

function formatDate(value) {
  if (!value) return '';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return '';
  return dt.toLocaleDateString('en-SG', { day: 'numeric', month: 'short', year: 'numeric' });
}

function formatDateTime(value) {
  if (!value) return '';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return '';
  return dt.toLocaleString('en-SG', { hour12: false });
}

function buildEventMessage(eventType, donor, details = {}) {
  const fullName = donor.fullName || 'Donor';
  const amount = formatMoney(donor.contribution || details.amount || details.newAmount || 0);
  const group = donor.group || 'Skim Pintar';
  const applicationId = donor.applicationId || details.applicationId || '';
  const cycle = details.cycle || '';
  const paymentDate = formatDate(details.paymentDate || details.dueDate || '');
  const reason = details.reason || '';

  const lines = {
    subscription_created: [
      `Assalamualaikum ${fullName},`,
      '',
      `Your Skim Pintar subscription has been received successfully.`,
      `Plan: ${group}`,
      `Monthly contribution: ${amount}`,
      applicationId ? `Application ID: ${applicationId}` : '',
      '',
      'Thank you for supporting Masjid Ar-Raudhah.'
    ],
    donation_amount_updated: [
      `Assalamualaikum ${fullName},`,
      '',
      'Your monthly donation amount has been updated.',
      `Previous amount: ${formatMoney(details.previousAmount || 0)}`,
      `New amount: ${formatMoney(details.newAmount || donor.contribution || 0)}`,
      '',
      'This update is now active in your account.'
    ],
    beneficiaries_added: [
      `Assalamualaikum ${fullName},`,
      '',
      `Beneficiary list updated: ${details.afterCount || 0} beneficiaries linked.`,
      'New beneficiary entries were added to your Skim Pintar Plus coverage.'
    ],
    beneficiaries_updated: [
      `Assalamualaikum ${fullName},`,
      '',
      'Your beneficiary details have been updated successfully.',
      `Current beneficiaries linked: ${details.afterCount || 0}.`
    ],
    beneficiaries_deleted: [
      `Assalamualaikum ${fullName},`,
      '',
      'Your beneficiary list has been updated.',
      `Remaining beneficiaries linked: ${details.afterCount || 0}.`
    ],
    donation_stopped: [
      `Assalamualaikum ${fullName},`,
      '',
      'Your request to stop the donation scheme has been processed.',
      reason ? `Reason: ${reason}` : '',
      '',
      'Future recurring deductions have been stopped.'
    ],
    payment_successful: [
      `Assalamualaikum ${fullName},`,
      '',
      `Payment received successfully for ${cycle || 'this cycle'}.`,
      paymentDate ? `Payment date: ${paymentDate}` : '',
      `Amount: ${amount}`,
      '',
      'Your coverage remains active.'
    ],
    payment_missed: [
      `Assalamualaikum ${fullName},`,
      '',
      `We have not received your payment for ${cycle || 'this cycle'} yet.`,
      paymentDate ? `Due date: ${paymentDate}` : '',
      `Amount due: ${amount}`,
      '',
      'Please take action to avoid interruption of coverage.'
    ],
    payment_overdue: [
      `Assalamualaikum ${fullName},`,
      '',
      `Your Skim Pintar payment is now overdue for ${cycle || 'this cycle'}.`,
      paymentDate ? `Original due date: ${paymentDate}` : '',
      `Outstanding amount: ${amount}`,
      '',
      'Please settle this urgently to maintain benefits.'
    ],
    payment_failed: [
      `Assalamualaikum ${fullName},`,
      '',
      `Payment attempt for ${cycle || 'this cycle'} has failed.`,
      paymentDate ? `Scheduled deduction date: ${paymentDate}` : '',
      `Amount: ${amount}`,
      '',
      'Please update your payment details or contact support immediately.'
    ],
    notification_preference_updated: [
      `Assalamualaikum ${fullName},`,
      '',
      `Your notification preference has been updated to ${String(details.channel || donor.notifyChannel || '').toUpperCase()}.`
    ],
    notification_test: [
      `Assalamualaikum ${fullName},`,
      '',
      'This is a test notification from your Skim Pintar account settings.',
      `Channel: ${String(details.channel || donor.notifyChannel || '').toUpperCase()}`,
      formatDateTime(details.requestedAt || details.timestamp || '') ? `Requested at: ${formatDateTime(details.requestedAt || details.timestamp || '')}` : '',
      '',
      'If you received this message, your selected notification channel is working.'
    ]
  };

  const body = (lines[eventType] || [
    `Assalamualaikum ${fullName},`,
    '',
    'Your Skim Pintar account was updated successfully.'
  ]).filter(Boolean).join('\n');

  const subjectMap = {
    subscription_created: 'Skim Pintar: Subscription Received',
    donation_amount_updated: 'Skim Pintar: Donation Amount Updated',
    beneficiaries_added: 'Skim Pintar: Beneficiaries Added',
    beneficiaries_updated: 'Skim Pintar: Beneficiaries Updated',
    beneficiaries_deleted: 'Skim Pintar: Beneficiaries Updated',
    donation_stopped: 'Skim Pintar: Donation Scheme Stopped',
    payment_successful: 'Skim Pintar: Payment Successful',
    payment_missed: 'Skim Pintar: Payment Missed',
    payment_overdue: 'Skim Pintar: Payment Overdue',
    payment_failed: 'Skim Pintar: Payment Failed',
    notification_preference_updated: 'Skim Pintar: Notification Preference Updated',
    notification_test: 'Skim Pintar: Test Notification'
  };

  return {
    subject: subjectMap[eventType] || 'Skim Pintar: Account Update',
    text: `${body}\n\nThis is an automated message.`
  };
}

function basicAuthHeader() {
  const token = Buffer.from(`${TWILIO_ACCOUNT_SID}:${TWILIO_AUTH_TOKEN}`).toString('base64');
  return `Basic ${token}`;
}

async function sendTwilioMessage({ to, from, body }) {
  if (!TWILIO_ACCOUNT_SID || !TWILIO_AUTH_TOKEN) {
    return { channel: 'twilio', status: 'skipped', detail: 'Twilio credentials not configured' };
  }
  const endpoint = `https://api.twilio.com/2010-04-01/Accounts/${TWILIO_ACCOUNT_SID}/Messages.json`;
  const params = new URLSearchParams({ To: to, From: from, Body: body });
  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: {
      Authorization: basicAuthHeader(),
      'Content-Type': 'application/x-www-form-urlencoded'
    },
    body: params.toString()
  });
  const contentType = String(resp.headers.get('content-type') || '');
  const payload = contentType.includes('application/json') ? await resp.json() : await resp.text();
  if (!resp.ok) {
    throw new Error(`Twilio API failed (${resp.status}): ${typeof payload === 'string' ? payload : JSON.stringify(payload)}`);
  }
  return payload;
}

async function sendWhatsAppReminder(phoneE164, text) {
  if (!TWILIO_WHATSAPP_FROM) {
    return { channel: 'whatsapp', status: 'skipped', detail: 'TWILIO_WHATSAPP_FROM not configured' };
  }
  if (!phoneE164) {
    return { channel: 'whatsapp', status: 'skipped', detail: 'Missing valid recipient phone' };
  }
  const payload = await sendTwilioMessage({
    to: `whatsapp:${phoneE164}`,
    from: TWILIO_WHATSAPP_FROM,
    body: text
  });
  return { channel: 'whatsapp', status: 'sent', sid: payload.sid || '' };
}

async function sendSmsReminder(phoneE164, text) {
  if (!TWILIO_SMS_FROM) {
    return { channel: 'sms', status: 'skipped', detail: 'TWILIO_SMS_FROM not configured' };
  }
  if (!phoneE164) {
    return { channel: 'sms', status: 'skipped', detail: 'Missing valid recipient phone' };
  }
  const payload = await sendTwilioMessage({
    to: phoneE164,
    from: TWILIO_SMS_FROM,
    body: text
  });
  return { channel: 'sms', status: 'sent', sid: payload.sid || '' };
}

async function sendEmailReminder(email, subject, text) {
  if (!email) return { channel: 'email', status: 'skipped', detail: 'Missing recipient email' };
  const emailFrom = getEmailFromAddress();
  if (!emailFrom) return { channel: 'email', status: 'skipped', detail: 'EMAIL_FROM not configured' };

  if (RESEND_API_KEY) {
    const resp = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${RESEND_API_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        from: emailFrom,
        to: [email],
        subject,
        text
      })
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(`Resend API failed (${resp.status}): ${JSON.stringify(payload)}`);
    return { channel: 'email', status: 'sent', id: payload.id || '' };
  }

  if (SENDGRID_API_KEY) {
    const resp = await fetch('https://api.sendgrid.com/v3/mail/send', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${SENDGRID_API_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        personalizations: [{ to: [{ email }] }],
        from: { email: emailFrom },
        subject,
        content: [{ type: 'text/plain', value: text }]
      })
    });
    if (!resp.ok) {
      const detail = await resp.text();
      throw new Error(`SendGrid API failed (${resp.status}): ${detail}`);
    }
    return { channel: 'email', status: 'sent', id: 'sendgrid' };
  }

  return { channel: 'email', status: 'skipped', detail: 'No email provider key configured' };
}

function pushDeliveryLog(store, entry) {
  if (!store.deliveryLog || !Array.isArray(store.deliveryLog)) store.deliveryLog = [];
  store.deliveryLog.unshift(entry);
  if (store.deliveryLog.length > STATE_MAX_LOGS) {
    store.deliveryLog.splice(STATE_MAX_LOGS);
  }
}

function sanitizeEventDonor(donor) {
  const item = donor && typeof donor === 'object' ? donor : {};
  return {
    applicationId: String(item.applicationId || '').trim(),
    fullName: String(item.fullName || '').trim(),
    nric: normalizeNric(item.nric || item.nricNormalized || ''),
    mobile: String(item.mobile || '').trim(),
    email: normalizeEmail(item.email || ''),
    notifyChannel: normalizeNotifyChannel(item.notifyChannel || ''),
    group: String(item.group || '').trim(),
    contribution: Number(item.contribution || 0)
  };
}

function findStoredDonorRecord(store, donor = {}) {
  const records = Array.isArray(store?.donors) ? store.donors : [];
  if (!records.length) return null;

  const applicationId = String(donor.applicationId || '').trim();
  const nric = normalizeNric(donor.nric || donor.nricNormalized || '');
  const email = normalizeEmail(donor.email || donor.authUserEmail || '');

  if (applicationId) {
    const byAppId = records.find(item => String(item?.applicationId || '').trim() === applicationId);
    if (byAppId) return byAppId;
  }
  if (nric) {
    const byNric = records.find(item => normalizeNric(item?.donor?.nric || item?.donor?.nricNormalized || '') === nric);
    if (byNric) return byNric;
  }
  if (email) {
    const byEmail = records.find(item => {
      const donorEmail = normalizeEmail(item?.donor?.email || '');
      const authEmail = normalizeEmail(item?.donor?.authUserEmail || '');
      return donorEmail === email || authEmail === email;
    });
    if (byEmail) return byEmail;
  }
  return null;
}

function hydrateEventDonor(store, donorInput) {
  const raw = donorInput && typeof donorInput === 'object' ? donorInput : {};
  const incoming = sanitizeEventDonor(raw);
  const matchedRecord = findStoredDonorRecord(store, incoming);
  if (!matchedRecord) return incoming;

  const fromStore = sanitizeEventDonor({
    applicationId: matchedRecord.applicationId || '',
    ...(matchedRecord.donor || {})
  });
  const merged = {
    ...fromStore,
    ...incoming
  };

  merged.applicationId = incoming.applicationId || fromStore.applicationId || '';
  if (!String(raw.notifyChannel || '').trim()) {
    merged.notifyChannel = fromStore.notifyChannel || incoming.notifyChannel || 'whatsapp';
  }
  if (!incoming.fullName && fromStore.fullName) merged.fullName = fromStore.fullName;
  if (!incoming.nric && fromStore.nric) merged.nric = fromStore.nric;
  if (!incoming.mobile && fromStore.mobile) merged.mobile = fromStore.mobile;
  if (!incoming.email && fromStore.email) merged.email = fromStore.email;
  if (!incoming.group && fromStore.group) merged.group = fromStore.group;
  if (!incoming.contribution && fromStore.contribution) merged.contribution = fromStore.contribution;
  return merged;
}

async function deliverByPreferredChannel(preferredChannel, donor, message) {
  const channel = normalizeNotifyChannel(preferredChannel || donor.notifyChannel || '');
  const phoneE164 = toSgE164(donor.mobile || '');
  const email = normalizeEmail(donor.email || '');

  if (channel === 'email') {
    return sendEmailReminder(email, message.subject, message.text);
  }
  if (channel === 'sms') {
    return sendSmsReminder(phoneE164, message.text);
  }
  return sendWhatsAppReminder(phoneE164, message.text);
}

function hasEventBeenSent(store, dedupeKey) {
  if (!dedupeKey) return false;
  const sent = store.sentEvents && typeof store.sentEvents === 'object' ? store.sentEvents : {};
  return Boolean(sent[dedupeKey]);
}

function markEventSent(store, dedupeKey, payload) {
  if (!dedupeKey) return;
  if (!store.sentEvents || typeof store.sentEvents !== 'object') store.sentEvents = {};
  store.sentEvents[dedupeKey] = {
    sentAt: new Date().toISOString(),
    ...(payload || {})
  };
}

async function dispatchEventNotification(store, { eventType, donor, details = {}, dedupeKey = '', manual = false, source = '' }) {
  const normalizedDonor = sanitizeEventDonor(donor);
  if (!normalizedDonor.fullName && !normalizedDonor.email && !normalizedDonor.mobile) {
    return { status: 'skipped', reason: 'missing_contact', dedupeKey };
  }

  if (dedupeKey && hasEventBeenSent(store, dedupeKey)) {
    return { status: 'duplicate', dedupeKey };
  }

  const message = buildEventMessage(eventType, normalizedDonor, details);
  let channelResult = null;
  try {
    channelResult = await deliverByPreferredChannel(normalizedDonor.notifyChannel, normalizedDonor, message);
  } catch (err) {
    channelResult = { channel: normalizedDonor.notifyChannel || 'whatsapp', status: 'failed', detail: err.message };
  }

  pushDeliveryLog(store, {
    timestamp: new Date().toISOString(),
    source: source || 'event',
    manual,
    dedupeKey,
    eventType,
    applicationId: normalizedDonor.applicationId || '',
    donorName: normalizedDonor.fullName || '',
    donorNric: normalizedDonor.nric || '',
    channelResult
  });

  if (channelResult && channelResult.status === 'sent') {
    markEventSent(store, dedupeKey, {
      eventType,
      applicationId: normalizedDonor.applicationId || '',
      channel: channelResult.channel || normalizedDonor.notifyChannel || ''
    });
    return { status: 'sent', channelResult, dedupeKey };
  }
  return { status: 'failed', channelResult, dedupeKey };
}

async function processReminders({ manual = false } = {}) {
  const store = readStore();
  const donors = Array.isArray(store.donors) ? store.donors : [];
  const now = new Date();

  let evaluated = 0;
  let dueNow = 0;
  let missed = 0;
  let overdue = 0;
  let failedState = 0;
  let sent = 0;
  let duplicates = 0;
  let failed = 0;

  for (const record of donors) {
    if (!record || record.terminatedAt) continue;
    evaluated += 1;
    const dueDate = getDueDateForCurrentMonth(record, now);
    if (!dueDate) continue;

    const daysLate = Math.floor((now.getTime() - dueDate.getTime()) / 86400000);
    const cycle = monthKey(dueDate);
    const donor = { ...(record.donor || {}), applicationId: record.applicationId || '' };
    const baseDetails = {
      cycle,
      dueDate: dueDate.toISOString(),
      amount: Number(donor.contribution || 0)
    };

    const tasks = [];
    if (daysLate === 0) {
      dueNow += 1;
      tasks.push({ eventType: 'payment_successful', dedupeKey: `${record.applicationId}:${cycle}:payment_successful` });
    }
    if (daysLate >= 1) {
      missed += 1;
      tasks.push({ eventType: 'payment_missed', dedupeKey: `${record.applicationId}:${cycle}:payment_missed` });
    }
    if (daysLate > OVERDUE_GRACE_DAYS) {
      overdue += 1;
      tasks.push({ eventType: 'payment_overdue', dedupeKey: `${record.applicationId}:${cycle}:payment_overdue` });
    }
    if (daysLate > OVERDUE_GRACE_DAYS + 7) {
      failedState += 1;
      tasks.push({ eventType: 'payment_failed', dedupeKey: `${record.applicationId}:${cycle}:payment_failed` });
    }

    for (const task of tasks) {
      const result = await dispatchEventNotification(store, {
        eventType: task.eventType,
        donor,
        details: baseDetails,
        dedupeKey: task.dedupeKey,
        manual,
        source: 'scheduled-cycle'
      });
      if (result.status === 'sent') sent += 1;
      if (result.status === 'duplicate') duplicates += 1;
      if (result.status === 'failed') failed += 1;
    }
  }

  writeStore(store);
  return {
    evaluated,
    dueNow,
    missed,
    overdue,
    failedState,
    sent,
    duplicates,
    failed,
    checkedAt: now.toISOString()
  };
}

function mergeDonors(incoming) {
  return Array.isArray(incoming) ? incoming.map(sanitizeDonorRecord).filter(Boolean) : [];
}

function sortedDonorRecords(records) {
  const list = Array.isArray(records) ? records.slice() : [];
  return list.sort((a, b) => {
    const left = String(a?.applicationId || '');
    const right = String(b?.applicationId || '');
    return left.localeCompare(right);
  });
}

function donorRecordsEqual(left, right) {
  return JSON.stringify(sortedDonorRecords(left)) === JSON.stringify(sortedDonorRecords(right));
}

const server = http.createServer(async (req, res) => {
  setCors(res);
  const parsedUrl = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
  const pathname = parsedUrl.pathname;
  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  if (pathname === '/health' && req.method === 'GET') {
    const store = readStore();
    sendJson(res, 200, {
      ok: true,
      donors: Array.isArray(store.donors) ? store.donors.length : 0,
      sentEvents: Object.keys(store.sentEvents || {}).length,
      configured: {
        sms: Boolean(TWILIO_ACCOUNT_SID && TWILIO_AUTH_TOKEN && TWILIO_SMS_FROM),
        whatsapp: Boolean(TWILIO_ACCOUNT_SID && TWILIO_AUTH_TOKEN && TWILIO_WHATSAPP_FROM),
        email: hasEmailProviderConfigured(),
        emailProvider: getEmailProvider() || null,
        emailFrom: getEmailFromAddress() || null
      }
    });
    return;
  }

  if (!isAuthorized(req)) {
    sendJson(res, 401, { ok: false, error: 'Unauthorized' });
    return;
  }

  if (pathname === '/api/sync/donors' && req.method === 'POST') {
    try {
      const body = await parseJsonBody(req);
      const incoming = Array.isArray(body.records) ? body.records : [];
      const store = readStore();
      const merged = mergeDonors(incoming);
      const unchanged = donorRecordsEqual(store.donors, merged);

      if (!unchanged) {
        store.donors = merged;
        store.lastSyncAt = new Date().toISOString();
        writeStore(store);
      }
      sendJson(res, 200, {
        ok: true,
        synced: incoming.length,
        stored: unchanged ? (Array.isArray(store.donors) ? store.donors.length : 0) : store.donors.length,
        lastSyncAt: store.lastSyncAt,
        unchanged
      });
    } catch (err) {
      sendJson(res, 400, { ok: false, error: err.message });
    }
    return;
  }

  if (pathname === '/api/notify/event' && req.method === 'POST') {
    try {
      const body = await parseJsonBody(req);
      const eventType = String(body.eventType || '').trim();
      if (!eventType) {
        sendJson(res, 400, { ok: false, error: 'Missing eventType.' });
        return;
      }

      const store = readStore();
      const donor = hydrateEventDonor(store, body.donor);
      const details = body.details && typeof body.details === 'object' ? body.details : {};
      const dedupeKey = String(body.dedupeKey || '').trim();

      const result = await dispatchEventNotification(store, {
        eventType,
        donor,
        details,
        dedupeKey,
        manual: true,
        source: 'api-event'
      });

      writeStore(store);
      sendJson(res, 200, {
        ok: true,
        eventType,
        dedupeKey,
        result
      });
    } catch (err) {
      sendJson(res, 400, { ok: false, error: err.message });
    }
    return;
  }

  if (pathname === '/api/reminders/run' && req.method === 'POST') {
    try {
      const result = await processReminders({ manual: true });
      sendJson(res, 200, { ok: true, ...result });
    } catch (err) {
      sendJson(res, 500, { ok: false, error: err.message });
    }
    return;
  }

  if (pathname === '/api/reminders/log' && req.method === 'GET') {
    const store = readStore();
    sendJson(res, 200, {
      ok: true,
      updatedAt: store.updatedAt,
      lastSyncAt: store.lastSyncAt,
      donors: Array.isArray(store.donors) ? store.donors.length : 0,
      sentEvents: store.sentEvents || {},
      sentCycles: store.sentCycles || {},
      logs: Array.isArray(store.deliveryLog) ? store.deliveryLog.slice(0, 200) : []
    });
    return;
  }

  sendJson(res, 404, { ok: false, error: 'Not found' });
});

server.on('error', err => {
  if (err && err.code === 'EADDRINUSE') {
    console.error(`[reminder-service] Port ${PORT} is already in use on ${HOST}.`);
    console.error('[reminder-service] Stop the existing process or run with another port, e.g. SP_REMINDER_PORT=8788.');
    process.exit(1);
  }
  console.error('[reminder-service] Server failed to start:', err?.message || err);
  process.exit(1);
});

server.listen(PORT, HOST, () => {
  console.log(`[reminder-service] listening on http://${HOST}:${PORT}`);
  console.log(`[reminder-service] data file: ${DATA_FILE}`);
  console.log(`[reminder-service] env file: ${LOCAL_ENV_FILE} (${fs.existsSync(LOCAL_ENV_FILE) ? 'found' : 'not found'})`);
  console.log(`[reminder-service] auth key required: ${API_KEY ? 'yes' : 'no'}`);
  console.log('[reminder-service] channels configured:', {
    sms: Boolean(TWILIO_ACCOUNT_SID && TWILIO_AUTH_TOKEN && TWILIO_SMS_FROM),
    whatsapp: Boolean(TWILIO_ACCOUNT_SID && TWILIO_AUTH_TOKEN && TWILIO_WHATSAPP_FROM),
    email: hasEmailProviderConfigured(),
    emailProvider: getEmailProvider() || null,
    emailFrom: getEmailFromAddress() || null
  });
});

setInterval(() => {
  processReminders().then(result => {
    if (result.sent > 0) {
      console.log('[reminder-service] reminders sent', result);
    }
  }).catch(err => {
    console.error('[reminder-service] reminder cycle failed', err.message);
  });
}, Math.max(1, CHECK_INTERVAL_MINUTES) * 60 * 1000);

setTimeout(() => {
  processReminders().catch(err => {
    console.error('[reminder-service] initial run failed', err.message);
  });
}, 3000);
