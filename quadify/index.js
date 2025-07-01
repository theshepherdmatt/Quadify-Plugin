'use strict';
const libQ = require('kew');
const { spawn } = require('child_process');
const path = require('path');

module.exports = QuadifyPlugin;

function QuadifyPlugin(context) {
  this.context = context;
  this.commandRouter = context.coreCommand;
  this.configManager = context.configManager;
  this.pythonProcess = null;
}

QuadifyPlugin.prototype.onStart = function () {
  const defer = libQ.defer();

  const python = '/usr/bin/python3';
  const script = path.join(__dirname, 'quadify', 'src', 'main.py');

  this.pythonProcess = spawn(python, [script]);

  this.pythonProcess.stdout.on('data', data =>
    this.commandRouter.logger.info('[Quadify Plugin] ' + data.toString())
  );

  this.pythonProcess.stderr.on('data', data =>
    this.commandRouter.logger.error('[Quadify Plugin ERROR] ' + data.toString())
  );

  this.pythonProcess.on('exit', code =>
    this.commandRouter.logger.info('[Quadify Plugin] Python process exited with code ' + code)
  );

  defer.resolve();
  return defer.promise;
};

QuadifyPlugin.prototype.onStop = function () {
  const defer = libQ.defer();

  if (this.pythonProcess) {
    this.pythonProcess.kill();
    this.commandRouter.logger.info('[Quadify Plugin] Python process killed');
  }

  defer.resolve();
  return defer.promise;
};
