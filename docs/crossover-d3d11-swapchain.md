# CrossOver: the D3D11 swapchain crash (`0x80070057`) and SSE Display Tweaks

Why Skyrim SE/AE can fail at start under **CrossOver on Apple Silicon** with
`D3D11CreateDeviceAndSwapChain failed: 0x80070057`, and how to fix it. Read it when the game dies before the main
menu with that message box. The one-line version is in `macos-crossover.md` section 5.

Tags are those of `macos-crossover.md`: **Measured (notes)** means observed by the maintainer on a CrossOver setup
and carried over from earlier notes, not re-run for this page.

## 1. The graphics chain

**Measured (notes)**

```
SkyrimSE.exe             DirectX 11 calls
  -> SKSE plugins        SSE Display Tweaks hooks D3D11CreateDeviceAndSwapChain
  -> DXVK                D3D11 -> Vulkan
  -> MoltenVK / D3DMetal Vulkan -> Metal
  -> macOS WindowServer / Apple Silicon GPU driver
```

Anything that changes the swapchain description on the way down is a candidate when the device cannot be created.

## 2. What the error is

`0x80070057` is `E_INVALIDARG` ("one or more arguments are invalid"). The message box is raised by SSE Display Tweaks,
not by the game: its create-device hook (`render.cpp`) calls the original `D3D11CreateDeviceAndSwapChain` and, on
`FAILED(hr)`, shows `D3D11CreateDeviceAndSwapChain failed: 0x%lX`.

Before that call the plugin rewrites the `DXGI_SWAP_CHAIN_DESC` (in `OnD3D11PreCreate`): buffer count, swap effect
(for example `DXGI_SWAP_EFFECT_FLIP_DISCARD`), flags (for example `ALLOW_TEARING`) and windowed/fullscreen. A
description that Wine's presentation layer rejects comes back as `E_INVALIDARG`.

## 3. Causes seen on macOS

**Measured (notes)**

| Cause | Detail |
|---|---|
| Conflicting INI flags | `SkyrimPrefs.ini` has `bFull Screen=1` together with `bBorderless=1` |
| Flip model not accepted | `SwapEffect=auto` picks `flip_discard`. Native Windows 10/11 accepts it; Wine/DXVK on some Metal configurations cannot negotiate the swap buffers for the window surface and rejects the call |
| Stale display session | After a Skyrim crash, or while another Metal app holds a swapchain, Wine's display driver can hang until the bottle is restarted |

## 4. Fix

**Measured (notes)**. Borderless windowed with `SwapEffect=discard` is the stable setup on Mac.

`Data/SKSE/Plugins/SSEDisplayTweaks.ini`:

```ini
[Render]
Fullscreen=false
Borderless=true
SwapEffect=discard
```

`SkyrimPrefs.ini`:

```ini
[Display]
bFull Screen=0
bBorderless=1
```

If the error persists with both set, restart the bottle (CrossOver: select the bottle, **Bottle > Restart Bottle**) to
clear a hung Vulkan/Metal surface, then start the game again.

Both INI files are in the INI hierarchy described in `CLAUDE.md`: `SkyrimPrefs.ini` loads last and wins.
