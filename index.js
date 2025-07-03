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

// --- ADD THESE HELPER FUNCTIONS & PATH HERE ---
const preferencePath = path.join(__dirname, 'quadifyapp', 'src', 'preference.json');

function loadPreference() {
  try {
    return fs.readJsonSync(preferencePath);
  } catch (e) {
    return {}; // default if file doesn't exist
  }
}

function savePreference(data) {
  fs.writeJsonSync(preferencePath, data, { spaces: 2 });
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

function extractValue(val) {
  if (val && typeof val === 'object' && 'value' in val) {
    return val.value;
  }
  return val;
}

ControllerQuadify.prototype.setUIConfig = function (data) {
  this.logger.info('[Quadify] setUIConfig called with: ' + JSON.stringify(data));
  this.config.set('enableCava',       logicValue(data.enableCava));
  this.config.set('enableButtonsLED', logicValue(data.enableButtonsLED));
  this.config.set('enableIR',         logicValue(data.enableIR));
  this.config.set('mcp23017_address', data.mcp23017_address);

  // Update preference.json too!
  const pref = loadPreference();
  pref.cava_enabled         = logicValue(data.enableCava);
  pref.display_mode         = extractValue(data.display_mode);        
  pref.clock_font_key       = extractValue(data.clock_font_key);     
  pref.show_seconds         = logicValue(data.show_seconds);
  pref.show_date            = logicValue(data.show_date);
  pref.screensaver_enabled  = logicValue(data.screensaver_enabled);
  pref.screensaver_type     = extractValue(data.screensaver_type);    
  pref.screensaver_timeout  = parseInt(data.screensaver_timeout, 10);
  pref.oled_brightness      = parseInt(data.oled_brightness, 10);
  savePreference(pref);

  // Feedback
  this.commandRouter.pushToastMessage('success', 'Settings Saved', 'Quadify settings updated.');
  return Promise.resolve({});
};


/** Casts “false”, false, 0 → false; everything else → true */
function logicValue(val) {
  if (typeof val === 'string') return val === 'true';
  return !!val;
}

ControllerQuadify.prototype.restartQuadify = function () {
  const self = this;
  self.logger.info('[Quadify] Restart requested via UI.');
  // You can use systemctl, or the built-in plugin restart if you prefer
  return libQ.nfcall(exec, 'sudo systemctl restart quadify.service')
    .then(() => {
      self.commandRouter.pushToastMessage('success', 'Quadify', 'Quadify service restarted.');
      return {};
    })
    .fail((err) => {
      self.logger.error('[Quadify] Failed to restart quadify.service: ' + err.message);
      self.commandRouter.pushToastMessage('error', 'Quadify', 'Failed to restart Quadify service.');
      throw err;
    });
};


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

ControllerQuadify.prototype.updateMcpConfig = function (data) {
  let addr = data.mcp23017_address;
  if (addr && !addr.startsWith('0x')) {
    addr = '0x' + addr;
  }

  // Update quadifyapp config.yaml for Python backend
  const cfg = this.loadConfigYaml();
  cfg.mcp23017_address = addr;
  this.saveConfigYaml(cfg);

  // Also update plugin config.json so UI and logic see same value
  this.config.set('mcp23017_address', addr);

  this.commandRouter.pushToastMessage(
    'success', 'Quadify', `MCP23017 address saved: ${addr}`
  );
  return libQ.resolve();
};

ControllerQuadify.prototype.autoDetectMCP = function () {
  const defer = libQ.defer();

  exec('i2cdetect -y 1', (err, stdout) => {
    if (err) {
      this.commandRouter.pushToastMessage('error', 'Quadify', 'i2cdetect failed');
      return defer.reject(err);
    }

    const lines = stdout.split('\n').slice(1); // skip header line
    let foundAddr = null;

    for (const line of lines) {
      const parts = line.trim().split(/\s+/);
      const row = parts[0].replace(':', '');
      for (let i = 1; i < parts.length; i++) {
        if (parts[i] !== '--') {
          // Calculate full address by adding row + column index
          foundAddr = '0x' + (parseInt(row, 16) + (i - 1)).toString(16);
          break;
        }
      }
      if (foundAddr) break;
    }

    if (!foundAddr) {
      this.commandRouter.pushToastMessage('error', 'Quadify', 'No MCP23017 board detected');

      // Clear address in configs
      const cfg = this.loadConfigYaml();
      cfg.mcp23017_address = '';
      this.saveConfigYaml(cfg);
      this.config.set('mcp23017_address', '');

      return defer.resolve();
    }

    // Save detected address to config.yaml
    const cfg = this.loadConfigYaml();
    cfg.mcp23017_address = foundAddr;
    this.saveConfigYaml(cfg);

    // Update plugin config.json too
    this.config.set('mcp23017_address', foundAddr);

    this.commandRouter.pushToastMessage('success', 'Quadify', 'Detected MCP23017 at ' + foundAddr);
    defer.resolve({ mcp23017_address: foundAddr });
  });

  return defer.promise;
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
