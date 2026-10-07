$ErrorActionPreference = 'Stop'
$PSVersionTable.PSVersion.ToString()
$taskWork = 'D:\Study\AI全栈开发\报告工作'
$wordReportApp = New-Object -ComObject Word.Application
$wordReportApp.Visible = $false
$wordReportApp.DisplayAlerts = 0
try {
  $templateDoc = $wordReportApp.Documents.Open('D:\Study\AI全栈开发\AI全栈开发实验1报告模板-2026-黄底红字请删除.doc',$false,$true)
  $templateDoc.Content.Text
  $templateDoc.SaveAs2((Join-Path $taskWork 'template.docx'),16)
  $templateDoc.ExportAsFixedFormat((Join-Path $taskWork 'template.pdf'),17)
  $templateDoc.Close($false)
} finally {
  $wordReportApp.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($wordReportApp) | Out-Null
}
