; installer.nsh — custom NSIS script included by electron-builder
; Writes the Windows long-path registry key so deeply nested model
; paths (>260 chars) work correctly.

!macro customInstall
  WriteRegDWORD HKLM "SYSTEM\CurrentControlSet\Control\FileSystem" \
    "LongPathsEnabled" 1
!macroend

!macro customUnInstall
  ; Leave the registry key — other apps may need it too
!macroend
