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

  // Load stored UI config
  self.config = self.configManager.getConfig();
  self.configYamlPath = path.join(__dirname, 'quadify', 'config.yaml');
}

// Lifecycle - on plugin start
ControllerQuadify.prototype.onStart = function() {
  this.logger.info('[Quadify] Plugin started');
  this.applyAllServiceToggles();
  return libQ.resolve();
};

// No special logic on stop
ControllerQuadify.prototype.onStop = function() {
  this.logger.info('[Quadify] Plugin stopped');
  return libQ.resolve();
};

// Config files used by plugin
ControllerQuadify.prototype.getConfigurationFiles = function() {
  return ['config.json'];
};

// Load UIConfig
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

// Called every time config UI is saved
ControllerQuadify.prototype.setUIConfig = function(data) {
  this.config = data; // Save to memory

  // Persist each setting
  this.configManager.setConfigValue('enableQuadify',    logicValue(data.enableQuadify));
  this.configManager.setConfigValue('enableCava',       logicValue(data.enableCava));
  this.configManager.setConfigValue('enableButtonsLED', logicValue(data.enableButtonsLED));
  this.configManager.setConfigValue('enableIR',         logicValue(data.enableIR));
  this.configManager.setConfigValue('mcp23017_address', data.mcp23017_address);

  this.applyAllServiceToggles();
  return libQ.resolve();
};

function logicValue(val) {
  if (typeof val === 'string') return val === 'true';
  return !!val;
}

// Unified service control
ControllerQuadify.prototype.controlService = function(service, enable) {
  const action = enable ? 'start' : 'stop';
  this.logger.info(`[Quadify] ${action}ing ${service}.service`);
  exec(`sudo systemctl ${action} ${service}.service`, (err) => {
    if (err) this.logger.error(`${service} service failed to ${action}`);
    else this.logger.info(`${service} service ${action}ed`);
  });
};

// Run toggles for all services
ControllerQuadify.prototype.applyAllServiceToggles = function() {
  this.controlService('quadify',             this.config.enableQuadify);
  this.controlService('cava',                this.config.enableCava);
  this.controlService('quadify_earlyled',    this.config.enableButtonsLED);
  this.controlService('quadify_ir',          this.config.enableIR);
};

// MCP23017 auto-detect button
ControllerQuadify.prototype.autoDetectMCP = function() {
  const self = this;
  const defer = libQ.defer();
  exec('i2cdetect -y 1', (err, stdout) => {
    if (err) {
      self.commandRouter.pushToastMessage('error', 'Quadify', 'i2cdetect failed');
      return defer.reject(err);
    }
    const m = stdout.match(/\b(20|21|22|23|24|25|26|27)\b/);
    if (!m) {
      self.commandRouter.pushToastMessage('error', 'Quadify', 'No MCP23017 found');
      return defer.reject('none');
    }
    const addr = `0x${m[0]}`;
    // Update config.yaml
    const cfg = self.loadConfigYaml();
    cfg.mcp23017_address = addr;
    self.saveConfigYaml(cfg);
    self.commandRouter.pushToastMessage('success', 'Quadify', `Detected MCP23017 at ${addr}`);
    defer.resolve({ success: true, address: addr });
  });
  return defer.promise;
};

// Save manual MCP address
ControllerQuadify.prototype.updateMcpConfig = function(data) {
  const self = this;
  const cfg = self.loadConfigYaml();
  cfg.mcp23017_address = data.mcp23017_address;
  self.saveConfigYaml(cfg);
  this.commandRouter.pushToastMessage('success', 'Quadify', 'MCP23017 address saved');
  return libQ.resolve();
};

// I18n and other handlers stay unchanged
ControllerQuadify.prototype.updateRotaryConfig = function(data) { /* existing implementation */ };
ControllerQuadify.prototype.updateIrConfig     = function(data) { /* existing implementation */ };

// YAML enable/save
ControllerQuadify.prototype.loadConfigYaml = function() {
  try {
    return yaml.load(fs.readFileSync(this.configYamlPath, 'utf8')) || {};
  } catch {
    return {};
  }
};
ControllerQuadify.prototype.saveConfigYaml = function(cfg) {
  fs.writeFileSync(this.configYamlPath, yaml.dump(cfg), 'utf8');
};

module.exports = ControllerQuadify;
