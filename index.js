'use strict';
const libQ = require('kew');
const fs = require('fs-extra');
const yaml = require('js-yaml');
const path = require('path');
const exec = require('child_process').exec;

function ControllerQuadify(context) {
  const self = this;
  self.context = context;
  self.commandRouter = self.context.coreCommand;
  self.logger = self.context.logger;
  self.configManager = self.context.configManager;

  self.config = self.configManager.getConfig();
  self.configYamlPath = path.join(__dirname, 'quadify', 'config.yaml');
}

// Lifecycle Hooks
ControllerQuadify.prototype.onVolumioStart = function() {
  return libQ.resolve();
};

ControllerQuadify.prototype.onStart = function() {
  this.logger.info('[Quadify] Plugin started');
  this.applyAllServiceToggles();
  return libQ.resolve();
};

ControllerQuadify.prototype.onStop = function() {
  this.logger.info('[Quadify] Plugin stopped');
  return libQ.resolve();
};

ControllerQuadify.prototype.getConfigurationFiles = function() {
  return ['config.json'];
};

// UIConfig loader
ControllerQuadify.prototype.getUIConfig = function() {
  const self = this;
  const defer = libQ.defer();
  const lang_code = self.commandRouter.sharedVars.get('language_code');
  self.commandRouter.i18nJson(
    path.join(__dirname, 'i18n/strings_' + lang_code + '.json'),
    path.join(__dirname, 'i18n/strings_en.json'),
    path.join(__dirname, 'UIConfig.json')
  ).then(uiconf => defer.resolve(uiconf))
   .fail(() => defer.reject(new Error()));
  return defer.promise;
};

ControllerQuadify.prototype.setUIConfig = function(data) {
  this.config = data;
  this.configManager.setConfigValue('enableQuadify', data.enableQuadify);
  this.configManager.setConfigValue('enableCava', data.enableCava);
  this.configManager.setConfigValue('enableButtonsLED', data.enableButtonsLED);
  this.configManager.setConfigValue('enableIR', data.enableIR);
  this.applyAllServiceToggles();
  return libQ.resolve();
};

// Helper to start/stop a systemd service
ControllerQuadify.prototype.controlService = function(service, enable) {
  const action = enable ? 'start' : 'stop';
  this.logger.info(`[Quadify] ${action}ing ${service}.service`);
  exec(`sudo systemctl ${action} ${service}.service`, (err, stdout, stderr) => {
    if (err) this.logger.error(`${service} error: ${stderr}`);
    else this.logger.info(`${service} ${action}ed successfully`);
  });
};

ControllerQuadify.prototype.applyAllServiceToggles = function() {
  this.controlService('quadify', this.config.enableQuadify);
  this.controlService('cava', this.config.enableCava);
  this.controlService('quadify_earlyled', this.config.enableButtonsLED);
  this.controlService('quadify_ir', this.config.enableIR);
};

// Config handlers (example: updating rotary, IR etc.)
ControllerQuadify.prototype.updateRotaryConfig = function(data) { /* existing code */ };
ControllerQuadify.prototype.updateIrConfig = function(data) { /* existing code */ };

// YAML helpers
ControllerQuadify.prototype.loadConfigYaml = function() {
  try {
    return yaml.load(fs.readFileSync(this.configYamlPath, 'utf8')) || {};
  } catch (e) {
    return {};
  }
};
ControllerQuadify.prototype.saveConfigYaml = function(config) {
  fs.writeFileSync(this.configYamlPath, yaml.dump(config), 'utf8');
};

module.exports = ControllerQuadify;
