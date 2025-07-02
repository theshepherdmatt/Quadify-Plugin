'use strict';

const libQ  = require('kew');
const fs    = require('fs-extra');
const yaml  = require('js-yaml');
const path  = require('path');
const exec  = require('child_process').exec;

function ControllerQuadify(context) {
  this.context        = context;
  this.commandRouter  = context.coreCommand;
  this.logger         = context.logger;
  this.configManager  = context.configManager;

  // Volumio’s persistent JSON settings
  this.config = this.configManager.getConfig() || {};

  // YAML file that the Python side (or shell scripts) may also read
  this.configYamlPath = path.join(__dirname, 'quadifyapp', 'config.yaml');
}

ControllerQuadify.prototype.onStart = function () {
  this.logger.info('[Quadify] Plugin starting…');
  return this.applyAllServiceToggles()
    .then(() => this.logger.info('[Quadify] Plugin started'));
};

ControllerQuadify.prototype.onStop = function () {
  this.logger.info('[Quadify] Plugin stopping…');
  /* Nothing asynchronous to clean up right now */
  return libQ.resolve();
};

ControllerQuadify.prototype.getConfigurationFiles = function () {
  return ['config.json'];
};

ControllerQuadify.prototype.getUIConfig = function () {
  const defer      = libQ.defer();
  const lang_code  = this.commandRouter.sharedVars.get('language_code');

  this.commandRouter.i18nJson(
    path.join(__dirname, `i18n/strings_${lang_code}.json`),
    path.join(__dirname, 'i18n/strings_en.json'),
    path.join(__dirname, 'UIConfig.json')
  )
  .then(uiconf => defer.resolve(uiconf))
  .fail(err     => defer.reject(err));

  return defer.promise;
};

ControllerQuadify.prototype.setUIConfig = function (data) {
  /* Persist to Volumio’s JSON storage */
  this.configManager.setConfigValue('enableQuadify',     logicValue(data.enableQuadify));
  this.configManager.setConfigValue('enableCava',        logicValue(data.enableCava));
  this.configManager.setConfigValue('enableButtonsLED',  logicValue(data.enableButtonsLED));
  this.configManager.setConfigValue('enableIR',          logicValue(data.enableIR));
  this.configManager.setConfigValue('mcp23017_address',  data.mcp23017_address);

  /* Keep an in-memory copy too */
  this.config = this.configManager.getConfig();

  return this.applyAllServiceToggles();
};

/** Casts “false”, false, 0 → false; everything else → true */
function logicValue(val) {
  if (typeof val === 'string') return val === 'true';
  return !!val;
}

function readBool(obj, key, fallback) {
  const raw = obj[key];
  if (raw === undefined) return fallback;
  return logicValue(raw);
}

ControllerQuadify.prototype.controlService = function (service, enable) {
  const action = enable ? 'start' : 'stop';
  const cmd    = `sudo systemctl ${action} ${service}.service`;

  return libQ.nfcall(exec, cmd)
    .then(() => this.logger.info(`[Quadify] ${service}.service ${action}ed`))
    .fail(err  => this.logger.error(`[Quadify] ${service}.service failed to ${action}: ${err.message}`));
};

ControllerQuadify.prototype.applyAllServiceToggles = function () {
  return libQ.all([
    this.controlService('quadify',            readBool(this.config, 'enableQuadify',    true)),
    this.controlService('cava',               readBool(this.config, 'enableCava',       false)),
    this.controlService('quadify_earlyled',   readBool(this.config, 'enableButtonsLED', false)),
    this.controlService('quadify_ir',         readBool(this.config, 'enableIR',         false))
  ]);
};

ControllerQuadify.prototype.autoDetectMCP = function () {
  const defer = libQ.defer();

  exec('i2cdetect -y 1', (err, stdout) => {
    if (err) {
      this.commandRouter.pushToastMessage('error', 'Quadify', 'i2cdetect failed');
      return defer.reject(err);
    }

    const m = stdout.match(/\b(20|21|22|23|24|25|26|27)\b/);
    if (!m) {
      this.commandRouter.pushToastMessage('error', 'Quadify', 'No MCP23017 found');
      return defer.reject(new Error('not found'));
    }

    const addr = `0x${m[0]}`;

    /* Update YAML */
    const cfg = this.loadConfigYaml();
    cfg.mcp23017_address = addr;
    this.saveConfigYaml(cfg);

    this.commandRouter.pushToastMessage('success', 'Quadify', `Detected MCP23017 at ${addr}`);
    defer.resolve({ mcp23017_address: addr });
  });

  return defer.promise;
};

ControllerQuadify.prototype.updateMcpConfig = function (data) {
  const cfg = this.loadConfigYaml();
  cfg.mcp23017_address = data.mcp23017_address;
  this.saveConfigYaml(cfg);

  this.commandRouter.pushToastMessage('success', 'Quadify', 'MCP23017 address saved');
  return libQ.resolve();
};

/* Stub handlers—fill these out as you add UI fields */
ControllerQuadify.prototype.updateRotaryConfig = function () { return libQ.resolve(); };
ControllerQuadify.prototype.updateIrConfig     = function () { return libQ.resolve(); };

ControllerQuadify.prototype.loadConfigYaml = function () {
  try {
    return yaml.load(fs.readFileSync(this.configYamlPath, 'utf8')) || {};
  } catch {
    return {};
  }
};

ControllerQuadify.prototype.saveConfigYaml = function (cfg) {
  fs.writeFileSync(this.configYamlPath, yaml.dump(cfg), 'utf8');
};

module.exports = ControllerQuadify;
