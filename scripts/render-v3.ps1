$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$sources = @(
    'docs/charter-v3.md',
    'docs/development-backlog-v3.md',
    'docs/contracts-v0.1.md',
    'collaboration/protocol.md',
    'docs/environment-baseline.md',
    'docs/verification/session-20261107.md'
)
$intro = @'
# 全球市场信息 Agent：V3 立项与多Agent开发执行计划

日期：2026-11-07｜首版A股研究优先｜协作方式：Codex主控 + 专项Agent + WorkBuddy独立工作包

本版合并立项价值、详细WBS、数据契约、开发协作协议和本轮真实执行记录。原V2方案保留。以下章节由对应源文档生成；后续修改源文档后运行scripts/render-v3.ps1重新生成。

本次交付：25项开发/验证任务、G0–G5闸门、机器可读任务板、WB-01探测交付及已通过15项测试的离线原型。真实采集、LLM、行情评价和持续运行尚未完成。

投入预算：90–147小时，约11–19个单人等效工作日；另设2–3日风险缓冲。7交易日运行验收另计，可与部分后续工作重叠；不按Agent数量直接折算完成日期。

'@
$sections = foreach ($source in $sources) {
    $text = Get-Content -LiteralPath (Join-Path $projectRoot $source) -Raw
    $text = [regex]::Replace($text, '(?m)^(#{1,5}) ', '$1# ')
    $text.Replace('../market-intel-agent-dev-plan-v2-20261107.md','market-intel-agent-dev-plan-v2-20261107.md')
}
$markdown = $intro + ($sections -join "`n`n---`n`n")
$stem = 'market-intel-agent-dev-plan-v3-20261107'
$mdPath = Join-Path $projectRoot "$stem.md"
[IO.File]::WriteAllText($mdPath, $markdown, [Text.UTF8Encoding]::new($false))
$body = (ConvertFrom-Markdown -LiteralPath $mdPath).Html
$script:planHeadingNumber = 0
$body = [regex]::Replace($body, '<h([1-6])(?: id="[^"]*")?>(.*?)</h\1>', [System.Text.RegularExpressions.MatchEvaluator]{
    param($match)
    $script:planHeadingNumber++
    '<h' + $match.Groups[1].Value + ' id="chapter-' + $script:planHeadingNumber + '">' + $match.Groups[2].Value + '</h' + $match.Groups[1].Value + '>'
})
$body = [regex]::Replace($body, '<table>(.*?)</table>', '<div class="table-wrap"><table>$1</table></div>', 'Singleline')
$toc = ([regex]::Matches($body, '<h2 id="([^"]+)">(.*?)</h2>') | ForEach-Object { '<a href="#' + $_.Groups[1].Value + '">' + $_.Groups[2].Value + '</a>' }) -join "`n"
$previousHtml = Get-Content -LiteralPath (Join-Path $projectRoot 'market-intel-agent-dev-plan-v2-20261107.html') -Raw
$css = [regex]::Match($previousHtml,'<style>(.*?)</style>','Singleline').Groups[1].Value
if (-not $css) { throw 'Missing document stylesheet' }
$html = @"
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>全球市场信息 Agent · V3 多Agent开发计划</title><style>$css</style></head><body>
<div class="layout"><aside aria-label="章节目录"><strong>立项与实施 · V3</strong>$toc</aside><main>
<div class="eyebrow">MULTI-AGENT DEVELOPMENT / V3</div>
<div class="summary"><strong>已开始协作：</strong>三个专项Agent完成审查与文档；WorkBuddy已交付独立探测，结果partial；离线合成链路15项测试通过。完整项目闸门尚未通过。</div>
$body
<footer>本HTML及Markdown由六份源文档合并生成，无需网络即可阅读。任务状态以collaboration/task-board.json及验收记录为准。合成样本不代表真实市场信息。</footer>
</main></div></body></html>
"@
$outPath = Join-Path $projectRoot "$stem.html"
[IO.File]::WriteAllText($outPath, $html, [Text.UTF8Encoding]::new($false))
$ids = [regex]::Matches($html, '\bid="([^"]+)"') | ForEach-Object { $_.Groups[1].Value }
if ($ids.Count -ne ($ids | Select-Object -Unique).Count) { throw 'Duplicate anchor IDs' }
foreach ($link in [regex]::Matches($html, 'href="#([^"]+)"')) {
    if ($ids -notcontains $link.Groups[1].Value) { throw 'Broken TOC link' }
}
[pscustomobject]@{ Html=$outPath; SourceDocuments=$sources.Count; Headings=$ids.Count; Bytes=(Get-Item -LiteralPath $outPath).Length }
