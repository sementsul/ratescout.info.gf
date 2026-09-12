# RateScout - interactive console rate monitor (Windows PowerShell).
# Keys: h heatmap, w watchlist, m movers; period 1/2/3 = 24h/7d/30d; r refresh, q quit.
# It only DOWNLOADS ready-made text pages from ratescout.ru and prints them. No install, no code from data.
# Source: https://ratescout.ru/cli/rs.ps1
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$base = "https://ratescout.ru/cli"; $view = "heat"; $period = "24h"
$wc = New-Object System.Net.WebClient; $wc.Encoding = [System.Text.Encoding]::UTF8
try { [Console]::CursorVisible = $false } catch {}
try {
  while ($true) {
    $p = if ($view -eq "watch") { "watch" } else { "$view-$period" }
    Clear-Host
    try { Write-Host ($wc.DownloadString("$base/$p.txt")) } catch { Write-Host "  no connection - press r to retry" }
    $k = [Console]::ReadKey($true).KeyChar
    switch ($k) {
      'h' { $view = "heat" } 'w' { $view = "watch" } 'm' { $view = "movers" }
      '1' { $period = "24h" } '2' { $period = "7d" } '3' { $period = "30d" }
      'q' { break }
    }
  }
} finally { try { [Console]::CursorVisible = $true } catch {} }
