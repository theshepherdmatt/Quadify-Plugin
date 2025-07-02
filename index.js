'use strict';

const libQ   = require('kew');
const fs     = require('fs-extra');
const yaml   = require('js-yaml');
const path   = require('path');
const exec   = require('child_process').exec;
const Vconf  = require('v-conf');

function ControllerQuadify(context) {
  this.context       = context;
  this.commandRouter = context.coreCommand;
  this.logger        = context.logger;
  this.config        = new Vconf();

  // YAML file that the Python side (or shell scripts) may also read
  this.configYamlPath = path.join(__dirname, 'quadifyapp', 'config.yaml');
}

// Called on Volumio start to load persistent JSON config
ControllerQuadify.prototype.onVolumioStart = function() {
  const defer = libQ.defer();
  this.logger.info('[Quadify] onVolumioStart');

  const configFile = this.commandRouter.pluginManager.getConfigurationFile(
    this.context,
    'config.json'
  );
  this.config.loadFile(configFile);
  defer.resolve();
  return defer.promise;
};

// Called when the plugin is enabled
ControllerQuadify.prototype.onStart = function () {
  this.logger.info('[Quadify] Plugin starting…');
  return this.applyAllServiceToggles()
    .then(() => this.logger.info('[Quadify] Plugin started'));
};

// Called when the plugin is disabled
ControllerQuadify.prototype.onStop = function () {
  this.logger.info('[Quadify] Plugin stopping…');
  return libQ.resolve();
};

// Optional restart handler
ControllerQuadify.prototype.onRestart = function () {
  return this.onStop().then(() => this.onStart());
};

ControllerQuadify.prototype.getConfigurationFiles = function () {
  return ['config.json'];
};

ControllerQuadify.prototype.getUIConfig = function () {
  const defer     = libQ.defer();
  const lang_code = this.commandRouter.sharedVars.get('language_code');

  this.commandRouter.i18nJson(
    path.join(__dirname, 'i18n/strings_' + lang_code + '.json'),
    path.join(__dirname, 'i18n/strings_en.json'),
    path.join(__dirname, 'UIConfig.json')
  )
    .then(uiconf => defer.resolve(uiconf))
    .fail(err     => defer.reject(err));

  return defer.promise;
};

ControllerQuadify.prototype.setUIConfig = function (data) {
  // Persist settings via v-conf
  this.config.set('enableQuadify',    logicValue(data.enableQuadify));
  this.config.set('enableCava',       logicValue(data.enableCava));
  this.config.set('enableButtonsLED', logicValue(data.enableButtonsLED));
  this.config.set('enableIR',         logicValue(data.enableIR));
  this.config.set('mcp23017_address', data.mcp23017_address);

  return this.applyAllServiceToggles();
};

/** Casts “false”, false, 0 → false; everything else → true */
function logicValue(val) {
  if (typeof val === 'string') return val === 'true';
  return !!val;
}

ControllerQuadify.prototype.controlService = function (service, enable) {
  const action = enable ? 'start' : 'stop';
  const cmd    = 'sudo systemctl ' + action + ' ' + service + '.service';

  return libQ.nfcall(exec, cmd)
    .then(() => this.logger.info(
      '[Quadify] ' + service + '.service ' + action + 'ed'
    ))
    .fail(err  => this.logger.error(
      '[Quadify] ' + service + '.service failed to ' + action + ': ' + err.message
    ));
};

ControllerQuadify.prototype.applyAllServiceToggles = function () {
  return libQ.all([
    this.controlService(
      'quadify',
      logicValue(this.config.get('enableQuadify'))
    ),
    this.controlService(
      'cava',
      logicValue(this.config.get('enableCava'))
    ),
    this.controlService(
      'quadify_earlyled',
      logicValue(this.config.get('enableButtonsLED'))
    ),
    this.controlService(
      'quadify_ir',
      logicValue(this.config.get('enableIR'))
    )
  ]);
};

ControllerQuadify.prototype.autoDetectMCP = function () {
  const defer = libQ.defer();

  exec('i2cdetect -y 1', (err, stdout) => {
    if (err) {
      this.commandRouter.pushToastMessage(
        'error', 'Quadify', 'i2cdetect failed'
      );
      return defer.reject(err);
    }

    const m = stdout.match(/\b(20|21|22|23|24|25|26|27)\b/);
    if (!m) {
      this.commandRouter.pushToastMessage(
        'error', 'Quadify', 'No MCP23017 found'
      );
      return defer.reject(new Error('not found'));
    }

    const addr = '0x' + m[0];

    // Update YAML config
    const cfg = this.loadConfigYaml();
    cfg.mcp23017_address = addr;
    this.saveConfigYaml(cfg);

    this.commandRouter.pushToastMessage(
      'success', 'Quadify', 'Detected MCP23017 at ' + addr
    );
    defer.resolve({ mcp23017_address: addr });
  });

  return defer.promise;
};

ControllerQuadify.prototype.updateMcpConfig = function (data) {
  const cfg = this.loadConfigYaml();
  cfg.mcp23017_address = data.mcp23017_address;
  this.saveConfigYaml(cfg);

  this.commandRouter.pushToastMessage(
    'success', 'Quadify', 'MCP23017 address saved'
  );
  return libQ.resolve();
};

// Stub handlers—fill these out as you add UI fields
ControllerQuadify.prototype.updateRotaryConfig = function () { return libQ.resolve(); };
ControllerQuadify.prototype.updateIrConfig     = function () { return libQ.resolve(); };

ControllerQuadify.prototype.loadConfigYaml = function () {
  try {
    return yaml.load(
      fs.readFileSync(this.configYamlPath, 'utf8')
    ) || {};
  } catch {
    return {};
  }
};

ControllerQuadify.prototype.saveConfigYaml = function (cfg) {
  fs.writeFileSync(
    this.configYamlPath,
    yaml.dump(cfg),
    'utf8'
  );
};

module.exports = ControllerQuadify;

