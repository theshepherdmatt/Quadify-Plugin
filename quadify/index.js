const { spawn } = require('child_process');
const fs = require('fs-extra');

let pythonProcess = null;

module.exports = class Quadify {
  onStart() {
    // Spawn the Python backend
    pythonProcess = spawn('python3', [__dirname + '/quadify/main.py'], {
      cwd: __dirname + '/quadify',
      stdio: 'inherit'
    });

    pythonProcess.on('error', (err) => {
      console.error('Failed to start Python process:', err);
    });

    pythonProcess.on('exit', (code, signal) => {
      console.log(`Python process exited with code ${code}, signal ${signal}`);
    });

    return Promise.resolve();
  }

  onStop() {
    // Clean up the Python process
    if (pythonProcess) {
      pythonProcess.kill();
      pythonProcess = null;
    }
    return Promise.resolve();
  }

  // (Optional) If you want config, logging, etc, add more methods!
};
