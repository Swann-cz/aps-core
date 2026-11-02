import fs from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { createServer } from 'vite'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import antd from 'antd'
import router from 'react-router-dom'

const ui = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const read = name => fs.readFileSync(path.join(ui, name), 'utf8')
async function loadTS(name) {
  const code = ts.transpileModule(read(name), { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText
  return import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'))
}
const { wizardStep } = await loadTS('src/pages/Wizard/state.ts')
const base = { id: 'check', name: '测试方案', created_at: '2026-10-28', state: 'READY', run: { state: 'IDLE', started_at: null, finished_at: '2026-10-28T00:00:00', seconds: 10, error: null }, no_plan: false, findings: [], plan_status: 'FEASIBLE', verdict: 'ACCEPT', hard_error_count: 0, solver: { name: 'segment', seconds: 10 }, objective: { L1a: 0, L1c: 0, L2: 1, L3a: 0, L3b: 0 }, formal: null }
const suggest = { stage: 'NO_GAP', next_mode: null, gaps: [], candidates: { saturdays: [], overtime: [] }, usage: null, baseline: null, current: null }
const states = [
  ['未选方案', undefined, undefined, 0],
  ['尚未运行', { ...base, state: 'NO_PLAN' }, undefined, 2],
  ['运行中', { ...base, run: { state: 'RUNNING' } }, undefined, 3],
  ['运行失败', { ...base, state: 'FAILED' }, undefined, 3],
  ['未排出计划', { ...base, no_plan: true }, undefined, 3],
  ['条件已改', { ...base, state: 'STALE' }, undefined, 2],
  ...['HAS_GAP', 'CANDIDATES_PENDING', 'CANDIDATES_DONE', 'EXHAUSTED'].map(stage => [stage, base, { stage }, 4]),
  ['无缺口', base, { stage: 'NO_GAP' }, 5],
  ['正式版', { ...base, formal: {} }, { stage: 'NO_GAP' }, 6],
  ['等待读取建议', base, undefined, 3],
  ['候选生成后条件已改', { ...base, state: 'STALE' }, { stage: 'CANDIDATES_PENDING' }, 2],
]
for (const [name, scenario, view, expected] of states) assert.equal(wizardStep(scenario, view), expected, name)
console.log('PASS 状态推导：14 项，包含运行中、失败、切换状态、候选生成后的条件变更和正式版')

const { core, FullPlanImportError } = await loadTS('src/api/core.ts')
const originalFetch = globalThis.fetch
try {
  const payload = new FormData()
  payload.append('file', new Blob(['test']), 'test.xlsx')
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/import/preview'); assert.equal(options.method, 'POST'); assert.equal(options.body, payload)
    return { ok: true, json: async () => ({ ok: true, errors: [], summary: {} }) }
  }
  assert.equal((await core.previewFullPlan(payload)).ok, true)
  globalThis.fetch = async () => ({ ok: false, json: async () => ({ detail: '预检服务错误', errors: [{ sheet: '期初在制', row: 2, column: '数量', message: 'PBS 期初 400 台' }] }) })
  await assert.rejects(core.previewFullPlan(payload), error => error instanceof FullPlanImportError && error.message === '预检服务错误' && error.errors[0].message.includes('PBS 期初 400 台'))
  globalThis.fetch = async () => { throw new TypeError('网络已断开') }
  await assert.rejects(core.previewFullPlan(payload), { message: '网络已断开' })
  console.log('PASS API包装：上传载荷、500错误明细、网络错误（模拟响应，未验证R11工作簿）')
} finally { globalThis.fetch = originalFetch }

const server = await createServer({ root: ui, server: { middlewareMode: true }, appType: 'custom' })
const originalError = console.error
const errors = []
console.error = (...args) => {
  if (String(args[0]).includes('useLayoutEffect does nothing on the server')) return
  errors.push(args.map(String).join(' '))
}
try {
  const { Wizard } = await server.ssrLoadModule('/src/pages/Wizard/index.tsx')
  const { CoreProvider, viewRevision } = await server.ssrLoadModule('/src/app/CoreContext.tsx')
  const { AppLayout } = await server.ssrLoadModule('/src/app/AppLayout.tsx')
  const { FormalVersions } = await server.ssrLoadModule('/src/pages/FormalVersions/index.tsx')
  function render(scenario, view = suggest, Component = Wizard) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    client.setQueryData(['core', 'scenarios'], scenario ? [scenario] : [])
    if (scenario) {
      client.setQueryData(['core', 'conditions', scenario.id], { scenario, conditions: [], options: { horizon: { start: '2026-01-01', end: '2026-12-31' }, caps: {}, workshops: [], nodes: [], auth_modes: [] } })
      client.setQueryData(['core', 'suggest', scenario.id, ...viewRevision(scenario)], view)
    }
    const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(antd.App, null, React.createElement(router.MemoryRouter, { initialEntries: ['/wizard'] }, React.createElement(CoreProvider, null, React.createElement(AppLayout, null, React.createElement(Component)))))))
    client.clear()
    return html
  }
  const checks = [
    ['导入', undefined, undefined, ['第 1 步', '自动检查', '其他导入方式', '创建方案，下一步']],
    ['条件', { ...base, state: 'NO_PLAN', plan_status: null }, undefined, ['第 3 步', '开始排产', '导入文件里没有条件']],
    ['条件变更', { ...base, state: 'STALE' }, undefined, ['第 3 步', '条件已改，需要重新运行']],
    ['运行', { ...base, state: 'RUNNING', run: { ...base.run, state: 'RUNNING', started_at: new Date().toISOString() } }, undefined, ['第 4 步', '已用', '一般 1–3 分钟', 'disabled']],
    ['失败', { ...base, state: 'FAILED', findings: ['测试失败原因'], run: { ...base.run, state: 'FAILED', error: '生成器异常退出' } }, undefined, ['没有排出计划', '测试失败原因', '回到排产条件', '重新运行']],
    ['缺口', base, { ...suggest, stage: 'HAS_GAP', next_mode: 'SINGLE_8P2' }, ['排出来了', '缺口与建议', '生成候选授权']],
    ['候选待运行', base, { ...suggest, stage: 'CANDIDATES_PENDING' }, ['运行候选排产', '撤销候选']],
    ['候选已运行', base, { ...suggest, stage: 'CANDIDATES_DONE', usage: { saturdays_used: [], saturdays_unused: [], overtime_used: [], overtime_unused_ids: [] } }, ['采纳：删掉没用到的候选', '全部撤销']],
    ['耗尽', base, { ...suggest, stage: 'EXHAUSTED' }, ['仍然定为正式版']],
    ['定稿', base, suggest, ['第 6 步', '全年缺口', '用时', '定为正式版', '定稿备注']],
    ['拒绝', { ...base, verdict: 'REJECT', hard_error_count: 2 }, suggest, ['计划没通过校验', '硬错误 2 条', '查看硬错误明细', '计划通过校验后才能定稿']],
    ['正式', { ...base, formal: { confirmed_at: '2026-10-28', source_id: 'source', note: '备注' } }, suggest, ['已定为正式版', '正式版本只读', '定稿完成']],
  ]
  for (const [name, scenario, view, texts] of checks) {
    const html = render(scenario, view)
    for (const text of texts) assert.ok(html.includes(text), name + ' 缺少 ' + text)
    assert.doesNotMatch(html.replace(/<[^>]*>/g, ''), /Filling|FEASIBLE|ACCEPT|L1a|L1c/)
    if (name === '正式') assert.doesNotMatch(html, /textarea|>开始排产<|>定为正式版<|>生成候选授权/)
  }
  const formal = render({ ...base, formal: { confirmed_at: '2026-10-28', source_id: 'source', note: '' } }, suggest, FormalVersions)
  assert.doesNotMatch(formal.replace(/<[^>]*>/g, ''), /Filling|FEASIBLE|ACCEPT|L1a|L1c/)
  assert.equal(errors.length, 0, errors.join('\n'))
  console.log('PASS SSR：13组初始渲染，含候选操作、正式版只读、顶栏及导航中文（非浏览器交互）')
} finally { console.error = originalError; await server.close() }

const app = read('src/app/App.tsx')
const css = read('src/styles.css')
assert.match(app, /fontSize: 15/)
assert.match(app, /controlHeight: 40/)
assert.match(app, /Navigate to="\/wizard"/)
assert.match(css, /height: 48px; min-width: 200px; max-width: 100%; font-size: 17px/)
assert.match(read('src/pages/Wizard/index.tsx'), /screens.lg \? 'horizontal' : 'vertical'/)
const assets = fs.readdirSync(path.join(ui, 'dist/assets'))
const builtJS = assets.filter(name => name.endsWith('.js')).map(name => read('dist/assets/' + name)).join('')
const builtCSS = assets.filter(name => name.endsWith('.css')).map(name => read('dist/assets/' + name)).join('')
for (const phrase of ['排产向导', '创建方案，下一步', '仍然定为正式版', '月度明细']) assert.ok(builtJS.includes(phrase), phrase)
assert.match(builtCSS, /height:48px;min-width:200px/)
console.log('PASS 产物与尺寸声明：向导路由、中文入口、15px主题、40px控件、48px主按钮、窄屏竖排')
console.log('检查结束：真实R10/R11上传、求解、采纳和浏览器布局仍待联调')
