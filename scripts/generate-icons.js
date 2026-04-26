const fs = require('fs');
const path = require('path');
const os = require('os');
const { Jimp } = require('jimp');
const pngToIcoModule = require('png-to-ico');
const pngToIco = pngToIcoModule.default || pngToIcoModule;

async function main() {
  const root = path.resolve(__dirname, '..');
  const srcPng = path.join(root, 'SilentSigmaLogo.png');
  const buildDir = path.join(root, 'build');
  const installerGuiDir = path.join(root, 'installer_gui');
  const appIco = path.join(buildDir, 'icon.ico');
  const installerIco = path.join(installerGuiDir, 'icon.ico');
  const installerLogoPng = path.join(installerGuiDir, 'SilentSigmaLogo.png');

  if (!fs.existsSync(srcPng)) {
    throw new Error(`Logo PNG not found: ${srcPng}`);
  }

  fs.mkdirSync(buildDir, { recursive: true });
  fs.mkdirSync(installerGuiDir, { recursive: true });

  // NSIS requires a valid ICO with standard icon sizes.
  const sizes = [16, 24, 32, 48, 64, 128, 256];
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'silentsigma-ico-'));
  const resizedPngs = [];
  const base = await Jimp.read(srcPng);
  for (const size of sizes) {
    const outPng = path.join(tempDir, `icon-${size}.png`);
    const img = base.clone().resize({ w: size, h: size });
    await img.write(outPng);
    resizedPngs.push(outPng);
  }
  const icoBuffer = await pngToIco(resizedPngs);

  fs.writeFileSync(appIco, icoBuffer);
  fs.writeFileSync(installerIco, icoBuffer);
  fs.copyFileSync(srcPng, installerLogoPng);
  fs.rmSync(tempDir, { recursive: true, force: true });

  console.log(`Generated icon: ${appIco}`);
  console.log(`Generated icon: ${installerIco}`);
  console.log(`Copied logo: ${installerLogoPng}`);
}

main().catch((err) => {
  console.error(err?.stack || err);
  process.exit(1);
});
