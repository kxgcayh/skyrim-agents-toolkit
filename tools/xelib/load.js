'use strict';

const fs = require('fs');
const path = require('path');

let cachedModule = null;
let cachedDir = null;

function loadXelib() {
    if (cachedModule) return cachedModule;

    const candidates = [];

    // (a) XEDITLIB_JS env (path to a package dir or xelib.js)
    if (process.env.XEDITLIB_JS) {
        let p = path.resolve(process.env.XEDITLIB_JS);
        try {
            if (fs.existsSync(p) && fs.statSync(p).isDirectory()) {
                p = path.join(p, 'xelib.js');
            }
        } catch (_) {}
        candidates.push({ spec: p, label: 'XEDITLIB_JS (' + p + ')', isPath: true });
    }

    // (b) tools/xeditlib/lib/xelib.js
    const fetchedPath = path.resolve(__dirname, '..', 'xeditlib', 'lib', 'xelib.js');
    candidates.push({ spec: fetchedPath, label: fetchedPath, isPath: true });

    // (c) require('xeditlib') for older installs
    candidates.push({ spec: 'xeditlib', label: 'xeditlib', isPath: false });

    const errors = [];
    let nativeLoadError = null;

    for (const cand of candidates) {
        if (cand.isPath) {
            try {
                if (!fs.existsSync(cand.spec)) {
                    errors.push(cand.label + ': file does not exist');
                    continue;
                }
            } catch (err) {
                errors.push(cand.label + ': ' + err.message);
                continue;
            }
        }

        try {
            const mod = require(cand.spec);
            cachedModule = mod;
            cachedDir = cand.isPath ? path.dirname(cand.spec) : path.dirname(require.resolve(cand.spec));
            loadXelib.dir = cachedDir;
            loadXelib.path = cand.spec;
            return cachedModule;
        } catch (e) {
            errors.push(cand.label + ': ' + e.message);
            const isModuleNotFound = e.code === 'MODULE_NOT_FOUND' &&
                (e.message.includes("'xeditlib'") || e.message.includes(cand.spec));
            const isNativeError = !isModuleNotFound && (
                e.code !== 'MODULE_NOT_FOUND' ||
                /dlopen|koffi|libXEditLib|XEditLib\.dll|\.dylib|\.dll|\.so/i.test(e.message)
            );
            if (isNativeError && !nativeLoadError) {
                nativeLoadError = e;
            }
        }
    }

    if (nativeLoadError) {
        throw new Error(
            'xeditlib is installed but its native library could not be loaded ('
            + process.platform + ' ' + process.arch + '). '
            + 'Bundled builds exist for win32 and darwin-arm64 only; XEDITLIB_PATH can point to another build. '
            + nativeLoadError.message
        );
    }

    const brief = errors.map(e => e.split('Require stack')[0].trim()).join(' | ');
    throw new Error(
        'xeditlib is not installed -- run "python3 tools/xeditlib/fetch.py" (and "npm ci --ignore-scripts --no-audit --no-fund" for koffi) '
        + 'from the toolkit root (every bundled script finds it by upward lookup). '
        + 'Tried: ' + brief
    );
}

module.exports = loadXelib;
