'use strict';

const libQ   = require('kew');
const fs     = require('fs-extra');
const yaml   = require('js-yaml');
const path   = require('path');
const exec   = require('child_process').exec;
const Vconf  = require('v-conf');

// --------- Paths ----------
const PLUGIN_ROOT        = __dirname;
const LIRC_CONFIGS_DIR   = path.join(PLUGIN_ROOT, 'quadifyapp', 'lirc', 'configurations');
const PREF_PATH          = path.join(PLUGIN_ROOT, 'quadifyapp', 'src', 'preference.json');
const YAML_PATH          = path.join(PLUGIN_ROOT, 'quadifyapp', 'config.yaml');
const USERCONFIG_TXT     = '/boot/userconfig.txt';
const IR_OVERLAY_LINE    = 'dtoverlay=gpio-ir,gpio_pin=27';

// ------------- Helpers ---------------
function logicValue(val) {
  if (typeof val === 'boolean') return val;
  if (typeof val === 'string') return val === 'true' || val === 'on' || val === '1';
  if (typeof val === 'number') return !!val;
  return false;
}
function flatten(val) {
  while (val && typeof val === 'object' && 'value' in val) val = val.value;
  return val;
}
function getFlatConfig(config) {
  const flat = {};
  Object.keys(config).forEach(key => {
    flat[key] = flatten(config[key]);
  });
  return flat;
}

// --- IR overlay helper ---
function ensureIrOverlayGpio27() {
  let content = '';
  try {
    content = fs.readFileSync(USERCONFIG_TXT, 'utf8');
  } catch (e) { content = ''; }
  const lines = content.split('\n').filter(line => !/^dtoverlay=gpio-ir/.test(line));
  lines.push(IR_OVERLAY_LINE);
  fs.writeFileSync(USERCONFIG_TXT, lines.filter(Boolean).join('\n') + '\n', 'utf8');
}

function ControllerQuadify(context) {
  this.context       = context;
  this.commandRouter = context.coreCommand;
  this.logger        = context.logger;
  this.config        = new Vconf();
  this.configFile    = '/data/configuration/music_service/quadify/config.json';
}

// ------------- Volumio Plugin Methods -------------

ControllerQuadify.prototype.onVolumioStart = function() {
  const defer = libQ.defer();
  this.logger.info('[Quadify] Using config file: ' + this.configFile);

  // Load config if exists, otherwise start empty
  let flatConfig = {};
  let changed = false;
  if (fs.existsSync(this.configFile)) {
    try {
      this.config.loadFile(this.configFile);
      flatConfig = getFlatConfig(this.config.get() || {});
      this.logger.info('[Quadify] Config loaded (flat): ' + JSON.stringify(flatConfig));
    } catch (e) {
      this.logger.error('[Quadify] Error loading config file: ' + e.message);
      flatConfig = {};
    }
  }

  // Define defaults for all expected keys
  const defaults = {
    enableCava: false,
    enableButtonsLED: false,
    enableIR: false,
    ir_remote_select: "",
    mcp23017_address: "0x20",
    display_mode: "modern",
    clock_font_key: "clock_sans",
    show_seconds: false,
    show_date: false,
    screensaver_enabled: false,
    screensaver_type: "geo",
    screensaver_timeout: 3600,
    oled_brightness: 200
  };

  // Set defaults for missing keys, preserve known values
  Object.keys(defaults).forEach(key => {
    if (flatConfig[key] === undefined) {
      this.config.set(key, defaults[key]);
      changed = true;
    } else {
      this.config.set(key, flatConfig[key]);
    }
  });

  // Remove any keys in the config that aren't in defaults (cleanup old/removed keys)
  Object.keys(flatConfig).forEach(key => {
    if (!(key in defaults)) {
      this.config.delete(key);
      changed = true;
    }
  });

  if (changed || !fs.existsSync(this.configFile)) {
    this.config.save(this.configFile);
    this.logger.info('[Quadify] Config updated with defaults/cleaned.');
  }

  defer.resolve();
  return defer.promise;
};


// ----------- UI Config + Dynamic Remotes -----------

ControllerQuadify.prototype.getAvailableIrRemotes = function() {
  try {
    return fs.readdirSync(LIRC_CONFIGS_DIR).filter(f =>
      fs.statSync(path.join(LIRC_CONFIGS_DIR, f)).isDirectory()
    );
  } catch (e) {
    this.logger.error('[Quadify] Failed to scan IR remotes: ' + e.message);
    return [];
  }
};

ControllerQuadify.prototype.getUIConfig = function () {
  try {
    const raw = fs.readFileSync(this.configFile, 'utf8');
    this.logger.info('[Quadify] UI flat config just before applying to UI: ' + JSON.stringify(flatConfig));
    this.logger.info('[Quadify] RAW config file content: ' + raw);
  } catch (e) {
    this.logger.error('[Quadify] Failed to read config file: ' + e.message);
  }
  const defer = libQ.defer();
  this.config.loadFile(this.configFile);
  const flatConfig = getFlatConfig(this.config.get() || {});
  const lang_code = this.commandRouter.sharedVars.get('language_code');
  const remotes = this.getAvailableIrRemotes().map(r => ({ label: r, value: r }));
  this.logger.info('[Quadify] UIConfig remotes: ' + JSON.stringify(remotes));

  this.commandRouter.i18nJson(
    path.join(__dirname, 'i18n/strings_' + lang_code + '.json'),
    path.join(__dirname, 'i18n/strings_en.json'),
    path.join(__dirname, 'UIConfig.json')
  )
    .then(uiconf => {
      // DISPLAY CONTROLS
      const displaySection = uiconf.sections.find(s => s.id === 'display_controls');
      if (displaySection) {
        displaySection.content.forEach(row => {
          if (row.id in flatConfig) row.value = flatConfig[row.id];
        });
      }
      // IR REMOTE SECTION
      const irSection = uiconf.sections.find(s => s.id === 'ir_remote_section');
      if (irSection) {
        irSection.content.forEach(row => {
          if (row.id === 'enableIR') row.value = flatConfig.enableIR;
          if (row.id === 'ir_remote_select') {
            row.options = remotes;
            row.value = flatConfig.ir_remote_select || (remotes[0]?.value || "");
          }
        });
      }
      // MCP23017 CONFIG
      const mcpSection = uiconf.sections.find(s => s.id === 'mcp23017_config');
      if (mcpSection) {
        mcpSection.content.forEach(row => {
          if (row.id in flatConfig) row.value = flatConfig[row.id];
        });
      }
      defer.resolve(uiconf);
    })
    .fail(err => defer.reject(err));
  return defer.promise;
};

// ------------- UIConfig Save Handler (ALWAYS FLAT) -------------

ControllerQuadify.prototype.setUIConfig = function (data) {
  this.logger.info('[Quadify] setUIConfig: ' + JSON.stringify(data));
  this.config.loadFile(this.configFile);
  const oldConfig = getFlatConfig(this.config.get() || {});
  const mergedConfig = {
    enableCava:          logicValue(data.enableCava      !== undefined ? flatten(data.enableCava)      : oldConfig.enableCava),
    enableButtonsLED:    logicValue(data.enableButtonsLED!== undefined ? flatten(data.enableButtonsLED): oldConfig.enableButtonsLED),
    enableIR:            logicValue(data.enableIR        !== undefined ? flatten(data.enableIR)        : oldConfig.enableIR),
    ir_remote_select:    data.ir_remote_select !== undefined ? flatten(data.ir_remote_select) : oldConfig.ir_remote_select,
    mcp23017_address:    data.mcp23017_address!== undefined ? flatten(data.mcp23017_address) : oldConfig.mcp23017_address,
    display_mode:        data.display_mode     !== undefined ? flatten(data.display_mode)     : oldConfig.display_mode,
    clock_font_key:      data.clock_font_key   !== undefined ? flatten(data.clock_font_key)   : oldConfig.clock_font_key,
    show_seconds:        logicValue(data.show_seconds    !== undefined ? flatten(data.show_seconds)    : oldConfig.show_seconds),
    show_date:           logicValue(data.show_date       !== undefined ? flatten(data.show_date)       : oldConfig.show_date),
    screensaver_enabled: logicValue(data.screensaver_enabled !== undefined ? flatten(data.screensaver_enabled) : oldConfig.screensaver_enabled),
    screensaver_type:    data.screensaver_type    !== undefined ? flatten(data.screensaver_type)    : oldConfig.screensaver_type,
    screensaver_timeout: data.screensaver_timeout !== undefined ? parseInt(flatten(data.screensaver_timeout), 10) : parseInt(oldConfig.screensaver_timeout, 10),
    oled_brightness:     data.oled_brightness     !== undefined ? parseInt(flatten(data.oled_brightness), 10)     : parseInt(oldConfig.oled_brightness, 10)
  };
  Object.keys(mergedConfig).forEach(key => {
    this.config.set(key, mergedConfig[key]);
  });
  this.config.save(this.configFile);
  this.commandRouter.pushToastMessage('success', 'Quadify', 'Configuration saved');
  return Promise.resolve({});
};

// ------------- IR Logic -------------

ControllerQuadify.prototype.setIrServiceState = function(enable) {
  const action = enable ? 'start' : 'stop';
  exec(`sudo systemctl ${action} ir_listener.service`, (err) => {
    if (err) {
      this.logger.error(`[Quadify] Failed to ${action} ir_listener: ` + err.message);
      this.commandRouter.pushToastMessage('error', 'Quadify', `Failed to ${action} IR listener.`);
    } else {
      this.logger.info(`[Quadify] IR listener ${action}ed`);
      this.commandRouter.pushToastMessage('success', 'Quadify', `IR listener ${action}ed.`);
    }
  });
};

ControllerQuadify.prototype.setIrRemote = function(data) {
  const remote = flatten(data.ir_remote_select);
  if (!remote) return libQ.reject('No remote specified');
  const confPath = path.join(LIRC_CONFIGS_DIR, remote, 'lircd.conf');
  const rcPath   = path.join(LIRC_CONFIGS_DIR, remote, 'lircrc');
  if (!fs.existsSync(confPath) || !fs.existsSync(rcPath)) {
    this.commandRouter.pushToastMessage('error', 'Quadify', 'Selected remote config not found.');
    return libQ.reject('Remote config missing');
  }
  try {
    fs.copySync(confPath, '/etc/lirc/lircd.conf');
    fs.copySync(rcPath,   '/etc/lirc/lircrc');
    exec('sudo systemctl restart lircd.service && sudo systemctl restart ir_listener.service', (err) => {
      if (err) {
        this.logger.error('[Quadify] Failed to restart IR services: ' + err.message);
        this.commandRouter.pushToastMessage('error', 'Quadify', 'Failed to restart IR services.');
      } else {
        this.commandRouter.pushToastMessage('success', 'Quadify', `IR remote set to ${remote}.`);
        this.config.set('ir_remote_select', remote);
      }
    });
  } catch (e) {
    this.commandRouter.pushToastMessage('error', 'Quadify', `Failed to set IR remote: ${e.message}`);
    return libQ.reject(e);
  }
  return libQ.resolve();
};

// ----------- Service Toggles (CAVA, Buttons, IR, etc) ------------

ControllerQuadify.prototype.controlService = function (service, enable) {
  const action = enable ? 'start' : 'stop';
  const cmd    = `sudo systemctl ${action} ${service}.service`;
  return libQ.nfcall(exec, cmd)
    .then(() => this.logger.info(`[Quadify] ${service}.service ${action}ed`))
    .fail(err => this.logger.error(`[Quadify] ${service}.service failed to ${action}: ${err.message}`));
};

ControllerQuadify.prototype.applyAllServiceToggles = function () {
  this.config.loadFile(this.configFile);
  const flatConfig = getFlatConfig(this.config.get() || {});
  return libQ.all([
    this.controlService('cava',       logicValue(flatConfig.enableCava)),
    this.controlService('early_led8', logicValue(flatConfig.enableButtonsLED)),
    this.controlService('ir_listener',logicValue(flatConfig.enableIR))
  ]);
};

// -------- MCP23017 Config, autodetect, YAML ---------

ControllerQuadify.prototype.updateMcpConfig = function (data) {
  let addr = data.mcp23017_address;
  if (addr && !addr.startsWith('0x')) addr = '0x' + addr;
  const cfg = this.loadConfigYaml();
  cfg.mcp23017_address = addr;
  this.saveConfigYaml(cfg);
  this.config.set('mcp23017_address', addr);
  this.commandRouter.pushToastMessage('success', 'Quadify', `MCP23017 address saved: ${addr}`);
  return libQ.resolve();
};

ControllerQuadify.prototype.autoDetectMCP = function () {
  const defer = libQ.defer();
  exec('i2cdetect -y 1', (err, stdout) => {
    if (err) {
      this.commandRouter.pushToastMessage('error', 'Quadify', 'i2cdetect failed');
      return defer.reject(err);
    }
    const lines = stdout.split('\n').slice(1);
    let foundAddr = null;
    for (const line of lines) {
      const parts = line.trim().split(/\s+/);
      const row = parts[0].replace(':', '');
      for (let i = 1; i < parts.length; i++) {
        if (parts[i] !== '--') {
          foundAddr = '0x' + (parseInt(row, 16) + (i - 1)).toString(16);
          break;
        }
      }
      if (foundAddr) break;
    }
    const cfg = this.loadConfigYaml();
    cfg.mcp23017_address = foundAddr || '';
    this.saveConfigYaml(cfg);
    this.config.set('mcp23017_address', foundAddr || '');
    if (!foundAddr) {
      this.commandRouter.pushToastMessage('error', 'Quadify', 'No MCP23017 board detected');
      return defer.resolve();
    }
    this.commandRouter.pushToastMessage('success', 'Quadify', 'Detected MCP23017 at ' + foundAddr);
    defer.resolve({ mcp23017_address: foundAddr });
  });
  return defer.promise;
};

ControllerQuadify.prototype.loadConfigYaml = function () {
  try { return yaml.load(fs.readFileSync(YAML_PATH, 'utf8')) || {}; }
  catch { return {}; }
};

ControllerQuadify.prototype.saveConfigYaml = function (cfg) {
  fs.writeFileSync(YAML_PATH, yaml.dump(cfg), 'utf8');
};

// --------- Misc/Stub handlers --------

ControllerQuadify.prototype.restartQuadify = function () {
  this.logger.info('[Quadify] Restart requested via UI.');
  return libQ.nfcall(exec, 'sudo systemctl restart quadify.service')
    .then(() => {
      this.commandRouter.pushToastMessage('success', 'Quadify', 'Quadify service restarted.');
      return {};
    })
    .fail((err) => {
      this.logger.error('[Quadify] Failed to restart quadify.service: ' + err.message);
      this.commandRouter.pushToastMessage('error', 'Quadify', 'Failed to restart Quadify service.');
      throw err;
    });
};

ControllerQuadify.prototype.updateRotaryConfig = function () { return libQ.resolve(); };

module.exports = ControllerQuadify;
