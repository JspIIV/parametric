// Prove Parametric end to end on GenLayer Asimov.
//
//   AT=0x... PADV=<padv pw> PPUB=<ppub pw> node scripts/prove.mjs
//
// padv underwrites policies; ppub takes them, paying the premium. A policy whose
// peril a public page shows occurred in the window pays the insured; one whose peril
// never occurs expires once the window closes; an untaken policy cannot be settled;
// an unreadable source leaves the policy active.
import { Wallet } from 'ethers';
import { createClient, createAccount } from 'genlayer-js';
import { testnetAsimov } from 'genlayer-js/chains';
import fs from 'fs';
import os from 'os';
import path from 'path';
import url from 'url';

const AT = process.env.AT;
const PADV = process.env.PADV || '';
const PPUB = process.env.PPUB || '';
if (!AT || !PADV || !PPUB) { console.error('set AT, PADV and PPUB'); process.exit(1); }

const ROOT = path.join(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const KS = path.join(os.homedir(), '.genlayer', 'keystores');
async function acct(file, pw) {
  const w = await Wallet.fromEncryptedJson(fs.readFileSync(path.join(KS, file), 'utf8'), pw);
  return { addr: w.address.toLowerCase(), client: createClient({ chain: testnetAsimov, account: createAccount(w.privateKey) }) };
}
const padv = await acct('padv.json', PADV);   // underwriter
const ppub = await acct('ppub.json', PPUB);    // insured
const anybody = createClient({ chain: testnetAsimov });

const RAW = 'https://raw.githubusercontent.com/JspIIV/parametric/master/docs/';
const now = () => Math.floor(Date.now() / 1000);
const FAR = () => String(now() + 3600);
const SOON = () => String(now() + 70);
const QUAKE = { peril: 'A magnitude 6.0 or greater earthquake strikes the Kestrel Basin.', url: RAW + 'quake-bulletin.txt' };
const HURRICANE = { peril: 'A hurricane makes landfall on the Marlin Coast.', url: RAW + 'no-landfall.txt' };
const FLOOD = { peril: 'A flood crests above five metres at the Halden gauge.', url: RAW + 'no-such-page-9f2c.txt' };

const out = [];
const say = l => { console.log(l); out.push(l); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const transient = e => /-32005|-32006|-32029|-32603|at capacity|rate limit|gas rate|reverted.*consensus|consensus.*reverted|backpressure|fetch failed|timeout|502|503|429|ECONNRESET|ENOTFOUND|EAI_AGAIN|getaddrinfo|resource not found/i
  .test(String(e?.details || e?.shortMessage || e?.message || e) + ' ' + String(e?.cause?.cause?.code || e?.cause?.code || ''));

async function read(fn, args = []) {
  for (let a = 1; ; a++) {
    try { return JSON.parse(await anybody.readContract({ address: AT, functionName: fn, args })); }
    catch (e) { if (!transient(e) || a >= 8) throw e; await sleep(4000 * a); }
  }
}
async function write(who, fn, args) {
  for (let a = 1; ; a++) {
    try { return await who.client.writeContract({ address: AT, functionName: fn, args, value: 0n }); }
    catch (e) { if (!transient(e) || a >= 8) throw e; say(`  (${fn} transient, wait ${8 * a}s)`); await sleep(8000 * a); }
  }
}
async function openPolicy(p, payout, premium, window) {
  const n = (await read('size')).total;
  for (let attempt = 1; attempt <= 3; attempt++) {
    await write(padv, 'open_policy', [p.peril, p.url, String(payout), String(premium), window]);
    for (let i = 0; i < 30; i++) { const s = await read('size'); if (s.total > n) return String(s.total - 1); await sleep(5000); }
    say('  (open not seen, retrying)');
  }
  throw new Error('policy not opened');
}
async function settleUntil(who, id, wantTerminal, label) {
  const before = await read('get', [id]);
  const beforeN = Number(before.settlements || 0);
  for (let attempt = 1; attempt <= 4; attempt++) {
    try { await write(who, 'settle', [id]); } catch (e) { say(`  ${label} err ${String(e.message).slice(0, 50)}`); }
    for (let i = 0; i < 36; i++) {
      await sleep(15000);
      const g = await read('get', [id]);
      if (wantTerminal && (g.status === 'PAID' || g.status === 'EXPIRED')) { say(`  ${label}: ${g.status} (${(i + 1) * 15}s)`); return g; }
      if (!wantTerminal && Number(g.settlements || 0) > beforeN) { say(`  ${label}: settled once (${(i + 1) * 15}s)`); return g; }
    }
    say(`  ${label}: not settled after poll, retrying`);
  }
  return await read('get', [id]);
}

say('Parametric, proven on GenLayer Asimov');
say('  contract ' + AT);
say('  underwriter(padv) ' + padv.addr + '  insured(ppub) ' + ppub.addr);
say('');

const baseUw = (await read('balance', [padv.addr])).balance;
const baseIn = (await read('balance', [ppub.addr])).balance;

// Open the expiring policy first so its short window elapses during the slow rounds.
const pExpire = await openPolicy(HURRICANE, 200, 10, SOON());
await write(ppub, 'take', [pExpire]);
say('opened #' + pExpire + ' (hurricane, short window) and ppub took it');

const pPay = await openPolicy(QUAKE, 100, 5, FAR());
await write(ppub, 'take', [pPay]);
say('opened #' + pPay + ' (quake) and ppub took it');

const pOpen = await openPolicy(QUAKE, 100, 5, FAR());
say('opened #' + pOpen + ' (left untaken, to test settling before a taker)');

const pUnread = await openPolicy(FLOOD, 50, 3, FAR());
await write(ppub, 'take', [pUnread]);
say('opened #' + pUnread + ' (unreadable source) and ppub took it');
say('');

say('settling the untaken policy #' + pOpen + ' (should be refused)...');
try { await write(padv, 'settle', [pOpen]); } catch (e) { say('  settle err ' + String(e.message).slice(0, 40)); }
await sleep(6000);
const openAfter = await read('get', [pOpen]);
say('  #' + pOpen + ' status: ' + openAfter.status + ' settlements: ' + openAfter.settlements);
say('');

say('settling the quake policy #' + pPay + '...');
const rPay = await settleUntil(ppub, pPay, true, 'quake');
say('  #' + pPay + ' status: ' + rPay.status + ' | ' + (rPay.reason || ''));
say('settling the flood policy #' + pUnread + ' (unreadable source)...');
const rUnread = await settleUntil(ppub, pUnread, false, 'flood');
say('  #' + pUnread + ' status: ' + rUnread.status + ' | verdict ' + rUnread.verdict);
say('');

const waitLeft = Number(await read('get', [pExpire]).then(p => p.window_end)) + 8 - now();
if (waitLeft > 0) { say('waiting ' + waitLeft + 's for the hurricane window to close...'); await sleep(waitLeft * 1000); }
say('settling the hurricane policy #' + pExpire + ' after its window...');
const rExpire = await settleUntil(padv, pExpire, true, 'hurricane');
say('  #' + pExpire + ' status: ' + rExpire.status + ' | ' + (rExpire.reason || ''));
say('');

const uw = (await read('balance', [padv.addr])).balance;
const ins = (await read('balance', [ppub.addr])).balance;
const size = await read('size');
say('underwriter balance ' + baseUw + ' -> ' + uw + ' (premiums earned)');
say('insured balance ' + baseIn + ' -> ' + ins + ' (payouts received)');
say('book: ' + JSON.stringify(size));

const checks = [
  ['a peril evidenced in the window pays the policy', rPay.status === 'PAID'],
  ['the payout is credited to the insured', ins - baseIn === 100],
  ['the premium of every taken policy is credited to the underwriter', uw - baseUw === 5 + 10 + 3],
  ['an untaken policy cannot be settled, it stays open', openAfter.status === 'OPEN' && Number(openAfter.settlements) === 0],
  ['a peril that never occurs expires once the window closes, paying nothing', rExpire.status === 'EXPIRED'],
  ['an unreadable source is UNCLEAR and leaves the policy active', rUnread.status === 'ACTIVE' && rUnread.verdict === 'UNCLEAR'],
  ['the book counts one paid policy and the units it paid', size.paid === 1 && size.paid_units === 100],
];
say('');
for (const [label, ok] of checks) say((ok ? '  ok   ' : ' FAIL  ') + label);
const failed = checks.filter(([, ok]) => !ok);
say('');
say(failed.length ? `${failed.length} of ${checks.length} checks failed` : `${checks.length} checks. The source triggered the payout inside its window, and nothing else did.`);

fs.mkdirSync(path.join(ROOT, 'results'), { recursive: true });
fs.writeFileSync(path.join(ROOT, 'results', 'proved.json'), JSON.stringify({
  proved_at: new Date().toISOString(), network: 'genlayer testnet asimov', contract: AT,
  paid: rPay, expired: rExpire, unreadable: rUnread, untaken: openAfter,
  underwriter_balance: uw, insured_balance: ins, size,
  checks: checks.map(([label, ok]) => ({ label, ok })), transcript: out,
}, null, 2));
say('Written to results/proved.json');
process.exit(failed.length ? 1 : 0);
