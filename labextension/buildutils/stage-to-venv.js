const path = require('path');
const fsExtra = require('fs-extra');
const fs = require('fs');

const packagePath = path.resolve(__dirname, '..');
const repoRoot = path.resolve(packagePath, '..');
const hasLinuxVenv = fs.existsSync(path.join(repoRoot, '.venv_linux'));
const venvName = hasLinuxVenv ? '.venv_linux' : '.venv';
const envPath = path.resolve(repoRoot, venvName, 'share', 'jupyter', 'labextensions', 'cellscope-lab');
const source = path.resolve(packagePath, 'labextension');

(async () => {
  await fsExtra.remove(envPath).catch(() => undefined);
  await fsExtra.mkdirp(envPath);
  await fsExtra.copy(source, envPath, { dereference: true });
  const install = {
    packageManager: 'npm',
    packageName: 'cellscope-lab',
    uninstallInstructions: 'Remove the cellscope repository editable install'
  };
  await fsExtra.writeJSON(path.join(envPath, 'install.json'), install, { spaces: 2 });
  console.log(`Staged ${packagePath} into ${envPath}`);
})();
