const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

(async () => {
  try {
    const browser = await puppeteer.launch({ headless: 'new' });
    const page = await browser.newPage();
    console.log('Navigating to Lido...');
    await page.goto('https://lido.fi', { waitUntil: 'networkidle2', timeout: 30000 });
    const html = await page.content();
    console.log('Success! HTML length:', html.length);
    console.log('Snippet:', html.substring(0, 200));
    await browser.close();
  } catch (err) {
    console.error('Stealth Puppeteer Error:', err);
  }
})();
