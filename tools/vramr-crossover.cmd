@echo off
rem vramr-crossover.cmd -- run VRAMr (Nexus 90557, v16.0310) under CrossOver/Wine, where its own script.bat dies:
rem the bottle has no powershell.exe, choice.exe or mode.com, and script.bat needs them for every prompt and folder
rem dialog. This runs the same seven VRAMr exes with the same arguments as script.bat, prompting with set /p instead.
rem
rem Add it in MO2 as an executable so the exes see the virtual Data folder (loose files from every mod):
rem   Binary:      C:\windows\system32\cmd.exe
rem   Arguments:   /c "Z:\<path to toolkit>\tools\vramr-crossover.cmd" [preset] [output root] [MO2 profile folder]
rem   Start in:    <game folder>\Data
rem preset is H, Q, O, P or V (the script.bat presets), or C followed by four resolutions (diffuse normal
rem parallax material; diffuse 512-4096, the rest 512-2048, powers of two, as script.bat's custom option):
rem   ... vramr-crossover.cmd C 2048 1024 1024 512 [output root] [MO2 profile folder]
rem Missing arguments are asked for, but under MO2 the console is hidden (Wine): pass them all there.
rem cmd /c strips the first and last quote of its command line when it holds more than two quotes, so the
rem MO2 Arguments field needs an extra outer pair: /c ""<script>" O D:\ "<profile>""
rem VRAMR_TOOLS overrides the tools folder (default: Data\VRAMr\tools, where the VRAMr mod puts it).
rem Retry: under MO2 some texconv starts fail with "Access denied. (os error 5)" (81 of 3121 in one run; cause not
rem found, not reproduced outside a full modlist). Those textures are left as copied originals, so after Optimise this
rem re-runs only them, up to 3 passes, through VRAMr's own Loose.exe + Optimise.exe on a separate folder: nothing is
rem encoded twice. R mode retries an existing output without MO2 (no virtual files are needed for it):
rem   ... vramr-crossover.cmd R O D:\        (R, then the preset or C d n p m the run used, then the output root)
rem GPU: texconv's DirectCompute BC7 encoder works on adapter 0 under CrossOver (measured), so GPU 0 is fixed.
setlocal EnableExtensions EnableDelayedExpansion

set "RetryOnly="
if /i "%~1"=="R" set "RetryOnly=1"
if defined RetryOnly shift
set "GameDir=%CD%"
if defined RetryOnly goto tools
if not exist "%GameDir%\..\Skyrim*.exe" (
  echo ERROR: start this in the game's Data folder. "%GameDir%\.." has no Skyrim exe.
  goto end
)
if exist "%GameDir%\VRAMrOutput.tmp" (
  echo ERROR: an earlier VRAMr output is enabled in your mod manager. Disable it and start again.
  goto end
)
:tools
set "ScriptDir=%VRAMR_TOOLS%"
if not defined ScriptDir set "ScriptDir=%GameDir%\VRAMr\tools"
rem outside MO2 (R mode) the virtual Data\VRAMr is absent: use the tools next to this script in the VRAMr mod
if not exist "%ScriptDir%\Optimise.exe" if exist "%~dp0VRAMr\tools\Optimise.exe" set "ScriptDir=%~dp0VRAMr\tools"
for %%e in (LayerPrep BSA Loose Exclude Filter Extract Optimise texconv) do if not exist "%ScriptDir%\%%e.exe" (
  echo ERROR: "%ScriptDir%\%%e.exe" missing. Is the VRAMr mod enabled, or VRAMR_TOOLS set?
  goto end
)

rem ---- preset (same table as script.bat)
set "Preset=%~1"
set "ArgOut=%~2"
set "ArgProfile=%~3"
if /i not "%Preset%"=="C" goto askpreset
set "ArgOut=%~6"
set "ArgProfile=%~7"
call :res Diffuse "%~2" 4096 || goto end
call :res Normal "%~3" 2048 || goto end
call :res Parallax "%~4" 2048 || goto end
call :res Material "%~5" 2048 || goto end
set "Preset=Custom"
:askpreset
if not defined Preset set /p "Preset=Preset: H=HQ 2K/2K/1K/1K  Q=Quality 2K/1K/1K/1K  O=Optimum 2K/1K/512/512  P=Performance 2K/512/512/512  V=Vanilla 512: "
if /i "%Preset%"=="H" (set "Diffuse=2048" & set "Normal=2048" & set "Parallax=1024" & set "Material=1024" & set "Preset=HQ")
if /i "%Preset%"=="Q" (set "Diffuse=2048" & set "Normal=1024" & set "Parallax=1024" & set "Material=1024" & set "Preset=Quality")
if /i "%Preset%"=="O" (set "Diffuse=2048" & set "Normal=1024" & set "Parallax=512" & set "Material=512" & set "Preset=Optimum")
if /i "%Preset%"=="P" (set "Diffuse=2048" & set "Normal=512" & set "Parallax=512" & set "Material=512" & set "Preset=Performance")
if /i "%Preset%"=="V" (set "Diffuse=512" & set "Normal=512" & set "Parallax=512" & set "Material=512" & set "Preset=Vanilla")
if not defined Diffuse (set "Preset=" & goto askpreset)

rem ---- output root: VRAMr makes <root>\VRAMr. Refuse an existing one instead of deleting it as script.bat offers.
set "OutRoot=%ArgOut%"
:askout
if not defined OutRoot set /p "OutRoot=Output drive or folder (VRAMr creates <it>\VRAMr; needs roughly the size of all your .dds), e.g. D:\ : "
if not defined OutRoot goto askout
if "%OutRoot:~-1%"=="\" set "OutRoot=%OutRoot:~0,-1%"
if not exist "%OutRoot%\" (echo "%OutRoot%" does not exist. & set "OutRoot=" & goto askout)
if defined RetryOnly goto retryonly
if exist "%OutRoot%\VRAMr" (
  echo ERROR: "%OutRoot%\VRAMr" exists from an earlier run. Rename or remove it yourself, then start again.
  goto end
)
set "VRAMrTEMP=%OutRoot%\VRAMr"

rem ---- mod manager: MO2 gets the layered BSA order from its profile, as in script.bat
set "ModMgr=Vortex"
tasklist /fi "ImageName eq ModOrganizer.exe" /fo csv 2>NUL | find /I "ModOrganizer.exe" >NUL && set "ModMgr=MO2"
set "MO2Profile=%ArgProfile%"
if not "%ModMgr%"=="MO2" goto haveprofile
:askprofile
if not defined MO2Profile set /p "MO2Profile=Active MO2 profile folder (the one holding modlist.txt): "
if not exist "%MO2Profile%\modlist.txt" (echo No modlist.txt in "%MO2Profile%". & set "MO2Profile=" & goto askprofile)
:haveprofile

mkdir "%VRAMrTEMP%\Logfiles" || goto end
set "Log=%VRAMrTEMP%\Logfiles\VRAMr.txt"
(
  echo VRAMr Started       : %DATE% %TIME%   [vramr-crossover.cmd]
  echo VRAMr Output folder : "%VRAMrTEMP%"
  echo ScriptDir           : "%ScriptDir%"
  echo GameDir             : "%GameDir%"
  echo Optimisation Preset : "%Preset%" %Diffuse% %Normal% %Parallax% %Material%
  echo Mod Manager         : %ModMgr% "%MO2Profile%"
) > "%Log%"
type "%Log%"
del "%TEMP%\Unpack-Order.tmp" >NUL 2>&1

rem ---- the pipeline: argument for argument what script.bat v16.0310 runs
cd /d "%GameDir%"
if "%ModMgr%"=="MO2" "%ScriptDir%\LayerPrep.exe" --profile "%MO2Profile%" --GameDir .\ --Logfile "%VRAMrTEMP%\Logfiles"
call :note "Indexing BSA Archives"
"%ScriptDir%\BSA.exe" --source .\*.bsa --dest "%VRAMrTEMP%\Output" --logfile "%VRAMrTEMP%\Logfiles" --layered "%TEMP%" --filter *.dds --db "%VRAMrTEMP%\Output\VRAMr.DB"
call :note "Layering Loose Textures"
"%ScriptDir%\Loose.exe" --source .\textures --dest "%VRAMrTEMP%\Output\textures" --logfile "%VRAMrTEMP%\Logfiles" --db "%VRAMrTEMP%\Output\VRAMr.DB"
call :note "Processing Exclusions"
"%ScriptDir%\Exclude.exe" --Exclude "%ScriptDir%\Exclusions.mod" --Dest "%VRAMrTEMP%\Output" --Logfile "%VRAMrTEMP%\Logfiles"
call :note "Filtering"
"%ScriptDir%\Filter.exe" --dnpm %Diffuse% %Normal% %Parallax% %Material% --Source "%VRAMrTEMP%\Output\VRAMr.db" --Logfiles "%VRAMrTEMP%\Logfiles"
call :note "Extracting Files"
"%ScriptDir%\Extract.exe" --Source "%VRAMrTEMP%\Output" --Logfile "%VRAMrTEMP%\Logfiles" --Output "%VRAMrTEMP%\Output"
call :note "Optimising Textures"
"%ScriptDir%\Optimise.exe" --dnpm %Diffuse% %Normal% %Parallax% %Material% --Source "%VRAMrTEMP%\Output\VRAMr.db" --Logfiles "%VRAMrTEMP%\Logfiles" --GPU 0 --Tool "%ScriptDir%\texconv.exe"
set "Root=%VRAMrTEMP%\Output"
call :retry

rem ---- tidy up as script.bat does: drop empty folders and the DB, add the marker, rename for the mod manager
cd /d "%VRAMrTEMP%\Output"
attrib -R -A -S -H *.* /s /d >NUL 2>&1
for /f "delims=" %%d in ('dir /s /b /ad ^| sort /r') do rd "%%d" >NUL 2>&1
copy /y "%ScriptDir%\VRAMrOutput.tmp" . >NUL
del *.db >NUL 2>&1
cd /d "%VRAMrTEMP%"
ren "Output" "DragNDropThisFolderIntoModManager"
echo %DATE% %TIME% VRAMr Complete... >> "%Log%"
echo.
echo VRAMr has finished. Install "%VRAMrTEMP%\DragNDropThisFolderIntoModManager" as a mod. Logs: "%VRAMrTEMP%\Logfiles"
goto end

:retryonly
set "VRAMrTEMP=%OutRoot%\VRAMr"
set "Root=%VRAMrTEMP%\DragNDropThisFolderIntoModManager"
if not exist "%Root%\" set "Root=%VRAMrTEMP%\Output"
if not exist "%Root%\textures\" (echo ERROR: no VRAMr output in "%VRAMrTEMP%". & goto end)
if not exist "%VRAMrTEMP%\Logfiles\Optimise.txt" (echo ERROR: no "%VRAMrTEMP%\Logfiles\Optimise.txt" to retry from. & goto end)
set "Log=%VRAMrTEMP%\Logfiles\VRAMr.txt"
call :retry
echo Retry finished. Logs: "%VRAMrTEMP%\Logfiles\Retry*"
goto end

:retry
rem Start from the newest log: Optimise.txt, or the last RetryN\Optimise.txt of an earlier pass (never redo those).
set "FailLog=%VRAMrTEMP%\Logfiles\Optimise.txt"
set /a Pass=0, Tries=0
:retrynewest
set /a Next=Pass+1
if exist "%VRAMrTEMP%\Logfiles\Retry%Next%\Optimise.txt" (set "Pass=%Next%" & set "FailLog=%VRAMrTEMP%\Logfiles\Retry%Next%\Optimise.txt" & goto retrynewest)
:retrypass
findstr /c:"Failed to execute texconv on " "%FailLog%" >nul || (call :note "No texconv start failures left" & exit /b 0)
if %Tries% GEQ 3 (call :note "WARNING: texconv start failures remain after 3 retries; those textures stay unoptimised, see %FailLog%" & exit /b 1)
set /a Pass+=1, Tries+=1
set "Work=%VRAMrTEMP%\Retry"
if exist "%Work%\" rd /s /q "%Work%"
mkdir "%VRAMrTEMP%\Logfiles\Retry%Pass%"
call :note "Retrying textures whose texconv start failed, pass %Pass%"
setlocal DisableDelayedExpansion
for /f "usebackq delims=" %%L in (`findstr /c:"Failed to execute texconv on " "%FailLog%"`) do call :stagefail "%%L"
endlocal
"%ScriptDir%\Loose.exe" --source "%Work%\textures" --dest "%Work%\textures" --logfile "%VRAMrTEMP%\Logfiles\Retry%Pass%" --db "%Work%\VRAMr.DB"
"%ScriptDir%\Optimise.exe" --dnpm %Diffuse% %Normal% %Parallax% %Material% --Source "%Work%\VRAMr.DB" --Logfiles "%VRAMrTEMP%\Logfiles\Retry%Pass%" --GPU 0 --Tool "%ScriptDir%\texconv.exe"
xcopy "%Work%\textures" "%Root%\textures\" /s /y /q >NUL
rd /s /q "%Work%"
set "FailLog=%VRAMrTEMP%\Logfiles\Retry%Pass%\Optimise.txt"
goto retrypass

:stagefail
rem %1: a log line "... Failed to execute texconv on textures/a b/c.dds: Access denied. (os error 5)"
set "Rel=%~1"
set "Rel=%Rel:*texconv on =%"
for /f "delims=:" %%p in ("%Rel%") do set "Rel=%%p"
set "Rel=%Rel:/=\%"
if not exist "%Root%\%Rel%" exit /b
for %%f in ("%Work%\%Rel%") do mkdir "%%~dpf" 2>NUL
copy /y "%Root%\%Rel%" "%Work%\%Rel%" >NUL
exit /b

:res
rem %1 variable name, %2 value, %3 maximum. 512..max, powers of two only (script.bat IsValidPowerOfTwo).
for %%r in (512 1024 2048 4096) do if "%~2"=="%%r" if %%r LEQ %3 (set "%1=%%r" & exit /b 0)
echo ERROR: %1 resolution "%~2" must be 512, 1024, 2048 or 4096, at most %3.
exit /b 1

:note
echo %DATE% %TIME% %~1...
echo %DATE% %TIME% %~1... >> "%Log%"
exit /b

:end
echo.
pause
