const puppeteer = require('puppeteer');
const fs = require('fs');

(async () => {
  try {
    const browser = await puppeteer.launch({ headless: 'new' });
    const page = await browser.newPage();
    await page.goto('https://lido.fi', { waitUntil: 'networkidle2', timeout: 30000 });
    const html = await page.content();
    fs.writeFileSync('lido.html', html);
    console.log('Saved lido.html, size:', html.length);
    await browser.close();
  } catch (err) {
    console.error('Puppeteer Error:', err);
  }
})();
