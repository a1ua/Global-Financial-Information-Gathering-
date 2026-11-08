param()
$ErrorActionPreference = 'Stop'
$stem = 'market-intel-agent-dev-plan-v2-20261107'
$mdPath = Join-Path $PSScriptRoot "$stem.md"
$outPath = Join-Path $PSScriptRoot "$stem.html"
$body = (ConvertFrom-Markdown -LiteralPath $mdPath).Html
$headings = [regex]::Matches($body, '<h2 id="([^"]+)">(.*?)</h2>')
$toc = ($headings | ForEach-Object { '<a href="#' + $_.Groups[1].Value + '">' + $_.Groups[2].Value + '</a>' }) -join "`n"
$body = [regex]::Replace($body, '<table>(.*?)</table>', '<div class="table-wrap"><table>$1</table></div>', 'Singleline')
$css = @'
:root{--ink:#172638;--muted:#53677c;--blue:#175b91;--line:#dce5ee;--paper:#fff;--bg:#f2f5f8}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.85,"Segoe UI","Microsoft YaHei",sans-serif}
.layout{max-width:1480px;margin:auto;display:grid;grid-template-columns:245px minmax(0,1fr);gap:30px;padding:30px}
aside{position:sticky;top:24px;align-self:start;max-height:92vh;overflow:auto;font-size:12px;padding:14px 0}aside strong{display:block;font-size:16px;margin:0 12px 12px}aside a{display:block;text-decoration:none;color:var(--muted);padding:7px 12px;border-radius:6px}aside a:hover{background:#e2ecf6;color:var(--blue)}
main{min-width:0;background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:38px 42px;box-shadow:0 8px 30px #17375607}.eyebrow{font-size:12px;letter-spacing:.14em;color:var(--blue);font-weight:700}.summary{background:#edf5fc;border-left:4px solid var(--blue);padding:15px 20px;border-radius:6px;margin:20px 0 30px}
h1{font-size:30px;line-height:1.45;margin:10px 0 20px}h2{font-size:23px;border-top:1px solid var(--line);padding-top:30px;margin-top:40px;line-height:1.5}h3{font-size:18px;margin-top:26px}p{margin:12px 0}a{color:var(--blue);overflow-wrap:anywhere}
.table-wrap{overflow-x:auto;margin:18px 0;border:1px solid var(--line);border-radius:8px}table{border-collapse:collapse;width:100%;min-width:650px;font-size:13px;line-height:1.75}th{text-align:left;background:#edf2f7;color:#203c55;padding:12px 14px}td{padding:12px 14px;vertical-align:top;border-top:1px solid var(--line)}tbody tr:nth-child(even){background:#fafcfe}td:first-child{font-weight:600;min-width:95px}pre{white-space:pre;overflow:auto;padding:22px;background:#152b40;color:#e0ebf5;border-radius:10px;line-height:1.7;font-size:13px}code{font-family:Consolas,"Microsoft YaHei",monospace}li{margin:8px 0}
.milestones{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:22px 0}.milestones div{padding:15px;border:1px solid var(--line);border-radius:8px;background:#fafcfe}.milestones b{display:block;color:var(--blue);font-size:16px}.milestones span{font-size:12px;color:var(--muted)}footer{margin-top:35px;border-top:1px solid var(--line);padding-top:20px;color:var(--muted);font-size:12px}
@media(max-width:1000px){.layout{display:block;padding:16px}aside{position:static;max-height:none;margin-bottom:20px}aside a{display:inline-block}main{padding:24px}.milestones{grid-template-columns:repeat(2,1fr)}}
@media(max-width:600px){h1{font-size:24px}h2{font-size:20px}main{padding:20px 16px}body{font-size:14px}}
@media print{body{background:white;font-size:10pt}.layout{display:block;padding:0}aside,.eyebrow{display:none}main{border:0;box-shadow:none;padding:0}h2{break-after:avoid}tr{break-inside:avoid}.table-wrap{overflow:visible}table{min-width:0;font-size:9pt}pre{white-space:pre-wrap;background:#f3f5f7;color:#172638}a{color:inherit;text-decoration:none}.milestones{grid-template-columns:repeat(4,1fr)}}
'@
$html = @"
<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>全球市场信息 Agent · V2.0 开发计划与任务流</title><style>$css</style></head>
<body><div class="layout"><aside aria-label="章节目录"><strong>开发计划 · V2.0</strong>$toc</aside><main>
<div class="eyebrow">MARKET INTELLIGENCE / IMPLEMENTATION PLAN</div>
<div class="summary"><strong>交付路线：</strong>先打通证据与简报，再冻结判断并核对后续结果。开发投入约10–15个工作日；运行验收至少7个交易日另计。数据源与工期在M0实测后确认。</div>
<div class="milestones"><div><b>M0 验证依赖</b><span>范围 · 来源 · 行情 · 日历</span></div><div><b>M1 简报 MVP</b><span>证据 · 生成 · 调度 · 降级</span></div><div><b>M2 可评价版本</b><span>冻结判断 · 对齐 · 核对</span></div><div><b>M3 运行交付</b><span>恢复 · 验收 · 操作手册</span></div></div>
$body
<footer>本文为开发方案，未执行数据源连通性验证、系统开发或前瞻有效性检验。Markdown为可维护源文件，本HTML由render-plan.ps1生成；无需外部脚本、字体或网络即可阅读。</footer>
</main></div></body></html>
"@
[IO.File]::WriteAllText($outPath, $html, [Text.UTF8Encoding]::new($false))
$ids = [regex]::Matches($html, '\bid="([^"]+)"') | ForEach-Object { $_.Groups[1].Value }
$duplicates = $ids | Group-Object | Where-Object Count -gt 1
if ($duplicates) { throw 'Duplicate heading IDs' }
foreach ($heading in $headings) {
  if ($ids -notcontains $heading.Groups[1].Value) { throw 'Broken section link' }
}
if ($headings.Count -ne 14) { throw 'Missing expected sections' }
foreach ($number in 1..12) {
  $task = 'T{0:00}' -f $number
  if (-not $body.Contains("<td>$task</td>")) { throw "Missing task $task" }
}
[pscustomobject]@{ Html=$outPath; Chapters=$headings.Count; Tables=([regex]::Matches($body,'<table>')).Count; Tasks=12; Bytes=(Get-Item -LiteralPath $outPath).Length }
