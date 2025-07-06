'use strict';

const libQ   = require('kew');
const fs     = require('fs-extra');
const yaml   = require('js-yaml');
const path   = require('path');
const exec   = require('child_process').exec;
const Vconf  = require('v-conf');

// --------- Paths ----------
const PLUGIN_ROOT = __dirname;
const LIRC_CONFIGS_DIR = path.join(PLUGIN_ROOT, 'quadifyapp', 'lirc', 'configurations');
const PREF_PATH = path.join(PLUGIN_ROOT, 'quadifyapp', 'src', 'preference.json');
const YAML_PATH = path.join(PLUGIN_ROOT, 'quadifyapp', 'config.yaml');
const USERCONFIG_TXT = '/boot/userconfig.txt';
const IR_OVERLAY_LINE = 'dtoverlay=gpio-ir,gpio_pin=27';

function ControllerQuadify(context) {
  this.context       = context;
  this.commandRouter = context.coreCommand;
  this.logger        = context.logger;
  this.config        = new Vconf();
  this.configFile    = this.commandRouter.pluginManager.getConfigurationFile(this.context, 'config.json');
}

// ------------- Helpers ---------------

function logicValue(val) {
  if (typeof val === 'string') return val === 'true';
  return !!val;
}

function extractValue(val) {
  if (val && typeof val === 'object' && 'value' in val) return val.value;
  return val;
}

function loadPreference() {
  try { return fs.readJsonSync(PREF_PATH); }
  catch (e) { return {}; }
}
function savePreference(data) {
  fs.writeJsonSync(PREF_PATH, data, { spaces: 2 });
}

// --- IR overlay helper ---
function ensureIrOverlayGpio27() {
  let content = '';
  try {
    content = fs.readFileSync(USERCONFIG, 'utf8');
  } catch (e) {
    // If the file doesn't exist, start fresh
    content = '';
  }
  const lines = content.split('\n')
    .filter(line => !/^dtoverlay=gpio-ir/.test(line));
  lines.push('dtoverlay=gpio-ir,gpio_pin=27');
  fs.writeFileSync(USERCONFIG, lines.filter(Boolean).join('\n') + '\n', 'utf8');
}

// ------------- Volumio Plugin Methods -------------

ControllerQuadify.prototype.onVolumioStart = function() {
  const defer = libQ.defer();
  this.config.loadFile(this.configFile);
  defer.resolve();
  return defer.promise;
};


ControllerQuadify.prototype.onStart = function () {
  this.logger.info('[Quadify] Plugin starting…');
  return this.applyAllServiceToggles()
    .then(() => this.logger.info('[Quadify] Plugin started'));
};

ControllerQuadify.prototype.onStop = function () {
  this.logger.info('[Quadify] Plugin stopping…');
  return libQ.resolve();
};
ControllerQuadify.prototype.onRestart = function () {
  return this.onStop().then(() => this.onStart());
};
ControllerQuadify.prototype.getConfigurationFiles = function () {
  return ['config.json'];
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
  const defer = libQ.defer();
  const lang_code = this.commandRouter.sharedVars.get('language_code');
  this.commandRouter.i18nJson(
    path.join(__dirname, 'i18n/strings_' + lang_code + '.json'),
    path.join(__dirname, 'i18n/strings_en.json'),
    path.join(__dirname, 'UIConfig.json')
  )
    .then(uiconf => {
      // ---- PATCH IN DYNAMIC REMOTE LIST ----
      const remotes = this.getAvailableIrRemotes().map(r => ({ label: r, value: r }));
      // Find IR section and patch options/value:
      uiconf.sections.forEach(section => {
        if (section.id === 'ir_remote_section') {
          // Add select if not present (preserves compatibility with your template)
          let found = false;
          for (const row of section.content) {
            if (row.id === 'ir_remote_select') {
              row.options = remotes;
              row.value = this.config.get('ir_remote_select') || (remotes[0]?.value || '');
              found = true;
            }
          }
          if (!found) {
            section.content.push({
              id: 'ir_remote_select',
              element: 'select',
              label: 'IR Remote Model',
              options: remotes,
              value: this.config.get('ir_remote_select') || (remotes[0]?.value || '')
            });
          }
        }
      });
      defer.resolve(uiconf);
    })
    .fail(err => defer.reject(err));
  return defer.promise;
};

// ------------- UIConfig Save Handler -------------

ControllerQuadify.prototype.setUIConfig = function (data) {
  console.log('[Quadify] configFile is:', this.configFile);
  this.logger.info('[Quadify] setUIConfig: ' + JSON.stringify(data));
  // Store toggles & addresses in plugin config
  this.config.set('enableCava',       logicValue(data.enableCava));
  this.config.set('enableButtonsLED', logicValue(data.enableButtonsLED));
  this.config.set('enableIR',         logicValue(data.enableIR));
  this.config.set('mcp23017_address', data.mcp23017_address);
  if (data.ir_remote_select) this.config.set('ir_remote_select', data.ir_remote_select);

  this.config.save(this.configFile);

  // Write preference.json for Python backend
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

  // IR Enable/Disable, and force gpio 27 overlay
  if (data.enableIR !== undefined) {
    this.setIrServiceState(logicValue(data.enableIR));
    if (logicValue(data.enableIR)) {
      try {
        ensureIrOverlayGpio27();
        this.logger.info('[Quadify] Ensured dtoverlay=gpio-ir,gpio_pin=27 in userconfig.txt');
      } catch (err) {
        this.logger.error('[Quadify] Could not update userconfig.txt: ' + err.message);
      }
    }
  }

  // If remote model is chosen, apply it
  if (data.ir_remote_select) {
    this.setIrRemote({ ir_remote_select: data.ir_remote_select });
  }

  this.commandRouter.pushToastMessage('success', 'Settings Saved', 'Quadify settings updated.');
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
  const remote = data.ir_remote_select;
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
  return libQ.all([
    this.controlService('cava',           logicValue(this.config.get('enableCava'))),
    this.controlService('early_led8',     logicValue(this.config.get('enableButtonsLED'))),
    this.controlService('ir_listener',    logicValue(this.config.get('enableIR')))
  ]);
};

// -------- MCP23017 Config, autodetect, YAML ---------

ControllerQuadify.prototype.updateMcpConfig = function (data) {
  let addr = data.mcp23017_address;
  if (addr && !addr.startsWith('0x')) addr = '0x' + addr;
  // Write config.yaml for Python
  const cfg = this.loadConfigYaml();
  cfg.mcp23017_address = addr;
  this.saveConfigYaml(cfg);
  // Also update plugin config.json so UI and logic see same value
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
    // Update configs
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
  const self = this;
  self.logger.info('[Quadify] Restart requested via UI.');
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

ControllerQuadify.prototype.updateRotaryConfig = function () { return libQ.resolve(); };

module.exports = ControllerQuadify;
