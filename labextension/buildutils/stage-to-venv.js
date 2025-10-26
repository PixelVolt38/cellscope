const path = require('path');
const fs = require('fs-extra');

const packagePath = path.resolve(__dirname, '..');
const envPath = path.resolve(packagePath, '..', '.venv', 'share', 'jupyter', 'labextensions', 'cellscope-lab');
const source = path.resolve(packagePath, 'labextension');

(async () => {
  await fs.remove(envPath).catch(() => undefined);
  await fs.mkdirp(envPath);
  await fs.copy(source, envPath, { dereference: true });
  const install = {
    packageManager: 'npm',
    packageName: 'cellscope-lab',
    uninstallInstructions: 'Remove the cellscope repository editable install'
  };
  await fs.writeJSON(path.join(envPath, 'install.json'), install, { spaces: 2 });
  console.log(`Staged ${packagePath} into ${envPath}`);
})();
