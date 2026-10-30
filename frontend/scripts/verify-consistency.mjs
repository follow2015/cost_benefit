// 独立验证脚本：用 esbuild 打包前端 calc-engine 的 harness（仓库唯一起源），
// 对 goldenVectors.json 跑一致性断言。
//
// 历史缺陷：本脚本曾内联生成一份只传 5 个选项的 harness 并覆盖仓库文件，
// 导致 GV14/GV15 误报失败。现 harness.ts 与选项组装（goldenOptions.ts）
// 均为仓库内受版本管理的文件，本脚本只负责打包执行，不再生成任何代码。
import { build } from 'esbuild';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, resolve as presolve } from 'path';

const root = dirname(fileURLToPath(import.meta.url)) + '/..';
const entry = presolve(root, 'src/features/calc/engine/__tests__/harness.ts');
const out = presolve(root, 'node_modules/.verify/bundle.cjs');

await build({
  entryPoints: [entry],
  bundle: true,
  outfile: out,
  platform: 'node',
  format: 'cjs',
  loader: { '.json': 'json' },
  logLevel: 'warning',
});
// Windows 下 `import('C:\\...')` 会被 ESM loader 拒绝（ERR_UNSUPPORTED_ESM_URL_SCHEME），
// 必须转成 file:// URL；Linux/macOS 下两者等价。
await import(pathToFileURL(out).href);
