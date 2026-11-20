import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

const tokensPath = path.join(rootDir, 'docs', 'design', 'tokens.json');
const tailwindConfigPath = path.join(rootDir, 'frontend', 'tailwind.config.ts');

if (!fs.existsSync(tokensPath)) {
  console.error(`Tokens file not found: ${tokensPath}`);
  process.exit(1);
}

if (!fs.existsSync(tailwindConfigPath)) {
  console.error(`Tailwind config file not found: ${tailwindConfigPath}`);
  process.exit(1);
}

const tokensData = JSON.parse(fs.readFileSync(tokensPath, 'utf8'));
const tailwindContent = fs.readFileSync(tailwindConfigPath, 'utf8');

console.log('=== CHECKING DESIGN TOKENS IN TAILWIND CONFIG ===\n');

// Target palette requirement
const targetPalette = {
  'paper': '#F6F3EE',
  'surface': '#FDFCFA',
  'line': '#E4DED5',
  'ink': '#1C1B19',
  'ink.soft': '#5E5A53',
  'ink.mute': '#706B63',
  'brand': '#115E59',
  'brand.hover': '#0B4745',
  'brand.soft': '#E3EFEE',
  'clay': '#D9733A',
  'clay.text': '#9A4A1E',
  'clay.soft': '#FBEFE6',
  'clay.line': '#EBCDB8',
  'sla.ok.bg': '#E6F0E8',
  'sla.ok.fg': '#25623A',
  'sla.ok.line': '#CFE0D3',
  'sla.risk.bg': '#FBF0D0',
  'sla.risk.fg': '#7A5200',
  'sla.risk.line': '#E8D58A',
  'sla.breach.bg': '#F8E1DE',
  'sla.breach.fg': '#9B1C1C',
  'sla.breach.line': '#EDB9B3',
  'sla.stop.bg': '#ECEAE6',
  'sla.stop.fg': '#55524C',
  'sla.stop.line': '#D6D2CB',
  'note.bg': '#F1EDF7',
  'note.border': '#D6CCE6',
  'note.lock': '#5B4A86',
  'priority.urgent': '#B42318',
  'priority.high': '#D9733A',
  'priority.medium': '#6B7C93',
  'priority.low': '#A8A196'
};

console.log(String('Role').padEnd(20) + ' | ' + String('Expected Hex').padEnd(12) + ' | In Tailwind Config? | Status');
console.log('-'.repeat(65));

let allMatch = true;

for (const [role, hex] of Object.entries(targetPalette)) {
  const hexUpper = hex.toUpperCase();
  const hexLower = hex.toLowerCase();
  const found = tailwindContent.toUpperCase().includes(hexUpper);
  
  const status = found ? 'MATCH' : 'FAIL';
  if (!found) allMatch = false;
  
  console.log(`${role.padEnd(20)} | ${hexUpper.padEnd(12)} | ${found ? 'Yes'.padEnd(19) : 'No'.padEnd(19)} | ${status}`);
}

console.log('\n--- Checking tokens.json namedColors ---');
const namedColors = tokensData.namedColors || {};
let dsMatches = 0;
let dsTotal = Object.keys(namedColors).length;

for (const [name, val] of Object.entries(namedColors)) {
  if (typeof val === 'string' && val.startsWith('#')) {
    const valUpper = val.toUpperCase();
    if (tailwindContent.toUpperCase().includes(valUpper)) {
      dsMatches++;
    }
  }
}
console.log(`tokens.json namedColors verified: ${dsMatches}/${dsTotal} found in tailwind config or mapped.`);

if (!allMatch) {
  console.log('\nResult: Some required target palette tokens are missing from tailwind.config.ts!');
  process.exit(1);
} else {
  console.log('\nResult: ALL required target palette tokens present in tailwind.config.ts! PASS');
  process.exit(0);
}
