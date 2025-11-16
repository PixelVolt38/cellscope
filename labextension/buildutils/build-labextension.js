const path = require('path');
const { spawn } = require('child_process');

const packagePath = path.resolve(__dirname, '..');
const repoRoot = path.resolve(packagePath, '..');
const fs = require('fs');
const hasLinuxVenv = fs.existsSync(path.join(repoRoot, '.venv_linux'));
const venvName = hasLinuxVenv ? '.venv_linux' : '.venv';
const resolveCorePath = () => {
  if (process.platform === 'win32') {
    return path.resolve(repoRoot, venvName, 'Lib', 'site-packages', 'jupyterlab', 'staging');
  }
  const libDir = path.resolve(repoRoot, venvName, 'lib');
  const pythonDirs = fs.existsSync(libDir)
    ? fs.readdirSync(libDir).filter(entry => entry.startsWith('python'))
    : [];
  const pyDir = pythonDirs.length ? pythonDirs[0] : 'python3';
  return path.resolve(libDir, pyDir, 'site-packages', 'jupyterlab', 'staging');
};
const corePath = resolveCorePath();
const isWindows = process.platform === 'win32';
const buildBin = isWindows ? 'build-labextension.cmd' : 'build-labextension';
const cmd = path.resolve(packagePath, 'node_modules', '.bin', buildBin);

const args = ['--core-path', corePath, packagePath];

const child = spawn(cmd, args, { stdio: 'inherit', shell: isWindows });

child.on('exit', code => {
  if (code !== 0) {
    process.exit(code ?? 1);
  }
});
