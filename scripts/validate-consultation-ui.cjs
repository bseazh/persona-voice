// Run with the existing Playwright module: node scripts/validate-consultation-ui.cjs
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const root = path.resolve(__dirname, '..');
  const password = fs.readFileSync(path.join(root, 'BigApple输出/consultation-access.txt'), 'utf8').split('管理员密码：')[1].split('\n')[0];
  const browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1365, height: 1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto('https://phone.hehaizhao.site/consult');
    await page.getByLabel('工作台管理员密码').fill(password);
    await page.getByRole('button', {name: '登录工作台', exact: true}).click();
    await page.getByRole('heading', {name: '每次沟通，都有据可查'}).waitFor();
    await page.getByRole('button', {name: '语音配置 · 填写 Key'}).click();
    await page.getByRole('heading', {name: '千问语音配置'}).waitFor();
    if (await page.getByLabel('共用 API Key').inputValue()) throw Error('Credential echoed');
    fs.mkdirSync(path.join(root,'BigApple输出/consultation-validation'), {recursive:true});
    await page.screenshot({path:path.join(root,'BigApple输出/consultation-validation/speech-settings.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    const overflow = await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    if(overflow) throw Error('Mobile page overflow');
    await page.getByRole('button', {name: '电话线路',exact:true}).click();
    await page.getByRole('button', {name:'拨打电话（尚未开放）'}).waitFor();
    if(!(await page.getByRole('button', {name:'拨打电话（尚未开放）'}).isDisabled()))throw Error('Dialing enabled');
    if(errors.length)throw Error(errors.join('\n'));
    console.log('PASS: public browser login, shared-key form, mobile layout, disabled dialing; no page errors.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exit(1);});
