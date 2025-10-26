const path = require('path');
const { spawn } = require('child_process');

const packagePath = path.resolve(__dirname, '..');
const corePath = path.resolve(packagePath, '..', '.venv', 'Lib', 'site-packages', 'jupyterlab', 'staging');
const cmd = path.resolve(packagePath, 'node_modules', '.bin', 'build-labextension.cmd');

const args = ['--core-path', corePath, packagePath];

const child = spawn(cmd, args, { stdio: 'inherit', shell: true });

child.on('exit', code => {
  if (code !== 0) {
    process.exit(code ?? 1);
  }
});
