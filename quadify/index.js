'use strict';
const libQ = require('kew');
const { exec } = require('child_process');

module.exports = QuadifyPlugin;
function QuadifyPlugin(context) {
  this.context = context;
  this.commandRouter = context.coreCommand;
}

QuadifyPlugin.prototype.onVolumioStart = function() {
  return this.commandRouter.loadUiConfig();
};

QuadifyPlugin.prototype.onStart = function() {
  const defer = libQ.defer();
  this.commandRouter.logger.info('Starting Quadify Plugin…');

  exec('systemctl start quadify.service', (err, stdout, stderr) => {
    if (err) {
      this.commandRouter.logger.error(`Error starting quadify.service: ${stderr}`);
      defer.reject(err);
    } else {
      this.commandRouter.logger.info('quadify.service started');
      defer.resolve();
    }
  });

  return defer.promise;
};

QuadifyPlugin.prototype.onStop = function() {
  const defer = libQ.defer();
  this.commandRouter.logger.info('Stopping Quadify Plugin…');

  exec('systemctl stop quadify.service', (err, stdout, stderr) => {
    if (err) {
      this.commandRouter.logger.error(`Error stopping quadify.service: ${stderr}`);
      defer.reject(err);
    } else {
      this.commandRouter.logger.info('quadify.service stopped');
      defer.resolve();
    }
  });

  return defer.promise;
};

QuadifyPlugin.prototype.getUIConfig = function() {
  const defer = libQ.defer();
  this.commandRouter.i18nJson(__dirname, 'i18n/strings.json',
    (err, uiConfig) => err ? defer.reject(err) : defer.resolve(uiConfig)
  );
  return defer.promise;
};

// No config save needed for now
QuadifyPlugin.prototype.onRestart = function() { return this.onStop().then(() => this.onStart()); };

