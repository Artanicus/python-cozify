"""Module for handling highlevel Cozify Hub operations.

Attributes:
    capability(capability): Enum of known device capabilities. Alphabetically sorted, numeric value not guaranteed to stay constant between versions if new capabilities are added.

"""

from absl import logging
import math
from . import config
from . import hub_api
from enum import Enum

from .Error import APIError

capability = Enum(
    'capability',
    'ALERT BASS BATTERY_U BRIGHTNESS COLOR_HS COLOR_LOOP COLOR_TEMP CONTACT CONTROL_LIGHT CONTROL_POWER DEVICE DIMMER_CONTROL GENERATE_ALERT HUE_SWITCH HUMIDITY IDENTIFY IKEA_RC LOUDNESS LUX MOISTURE MOTION MUTE NEXT ON_OFF PAUSE PLAY PREVIOUS PUSH_NOTIFICATION REMOTE_CONTROL SEEK SMOKE STOP TEMPERATURE TRANSITION TREBLE TWILIGHT UPGRADE USER_PRESENCE VOLUME'
)

### Device data ###


def devices(*, capabilities=None, and_filter=False, devs=None, **kwargs):
    """Get up to date full devices data set as a dict. Optionally can be filtered to only include certain devices.

    Args:
        capabilities(cozify.hub.capability): Single or list of cozify.hub.capability types to filter by, for example: [ cozify.hub.capability.TEMPERATURE, cozify.hub.capability.HUMIDITY ]. Defaults to no filtering.
        and_filter(bool): Multi-filter by AND instead of default OR. Defaults to False.
        devs(dict): Optional devices dictionary to use. If not defined, will be retrieved live.
        **hub_name(str): optional name of hub to query.
        **hub_id(str): optional id of hub to query. A specified hub_id takes presedence over a hub_name or default Hub. Providing incorrect hub_id's will create cruft in your state but it won't hurt anything beyond failing the current operation.
        **remote(bool): Remote or local query.

    Returns:
        dict: full live devices dictionary as returned by the API

    """
    _fill_kwargs(kwargs)

    if devs is None:
        devs = hub_api.devices(**kwargs)
    if capabilities:
        if isinstance(capabilities, capability):  # single capability given
            return {
                key: value
                for key, value in devs.items()
                if capabilities.name in value['capabilities']['values']
            }
        else:  # multi-filter
            if and_filter:
                return {
                    key: value
                    for key, value in devs.items()
                    if all(c.name in value['capabilities']['values'] for c in capabilities)
                }
            else:  # or_filter
                return {
                    key: value
                    for key, value in devs.items()
                    if any(c.name in value['capabilities']['values'] for c in capabilities)
                }
    else:  # no filtering
        return devs


def device_reachable(device_id, devs=None, state=None, **kwargs):
    """Check if device exists and is reachable.

    Args:
        device_id(str): ID of the device to check.
        devs(dict): Optional devices dictionary to use. If not defined, will be retrieved live.
        state(dict): Optional state dictionary, will be updated with state of checked device if device is eligible. Previous data in the dict is preserved unless it's overwritten by new values.
    Returns:
        bool: True if filter matches.
    """
    _fill_kwargs(kwargs)

    if devs is None:  # only retrieve if we didn't get them
        devs = devices(**kwargs)
    if state is None:
        state = {}  # enable storing values since we need to get reachability
    if device_exists(device_id, state=state, devs=devs, **kwargs):
        return state['reachable']
    else:
        raise ValueError('Device not found: {}'.format(device_id))


def device_exists(device_id, devs=None, state=None, **kwargs):
    """Check if device exists.

    Args:
        device_id(str): ID of the device to check.
        devs(dict): Optional devices dictionary to use. If not defined, will be retrieved live.
        state(dict): Optional state dictionary, will be updated with state of checked device if device is eligible. Previous data in the dict is preserved unless it's overwritten by new values.
    Returns:
        bool: True if filter matches.
    """
    if devs is None:  # only retrieve if we didn't get them
        devs = devices(**kwargs)
    if device_id in devs:
        if state is not None:
            state.update(devs[device_id]['state'])
            logging.debug('Implicitly returning state: {0}'.format(state))
        return True
    else:
        return False


def device_eligible(device_id, capability_filter, devs=None, state=None, **kwargs):
    """Check if device matches a AND devices filter.

    Args:
        device_id(str): ID of the device to check.
        capability_filter(hub.capability): Single hub.capability or a list of them to match against.
        devs(dict): Optional devices dictionary to use. If not defined, will be retrieved live.
        state(dict): Optional state dictionary, will be updated with state of checked device if device is eligible. Previous data in the dict is preserved unless it's overwritten by new values.
    Returns:
        bool: True if filter matches.
    """

    # Even if we already have a devs dict it still needs to get filtered
    devs = devices(capabilities=capability_filter, devs=devs, **kwargs)
    if device_id in devs:
        if state is not None:
            state.update(devs[device_id]['state'])
            logging.debug('Implicitly returning state: {0}'.format(state))
        return True
    else:
        return False


### Device control ###


def device_toggle(device_id, **kwargs):
    """Toggle power state of any device capable of it such as lamps. Eligibility is determined by the capability ON_OFF.

    Args:
        device_id(str): ID of the device to toggle.
        **hub_id(str): optional id of hub to operate on. A specified hub_id takes presedence over a hub_name or default Hub.
        **hub_name(str): optional name of hub to operate on.
        **remote(bool): Remote or local query.
    """
    _fill_kwargs(kwargs)

    # Get list of devices known to support toggle and find the device and it's state.
    devs = devices(capabilities=capability.ON_OFF, **kwargs)
    dev_state = devs[device_id]['state']
    current_power = dev_state['isOn']
    new_state = _clean_state(dev_state)
    new_state['isOn'] = not current_power  # reverse power state
    hub_api.devices_command_state(device_id=device_id, state=new_state, **kwargs)


def device_state_replace(device_id, state, **kwargs):
    """Replace the entire state of a device with the provided state. Useful for example for returning to a stored state.

    Args:
        device_id(str): ID of the device to toggle.
        state(dict): State dictionary to push out.
        **hub_id(str): optional id of hub to operate on. A specified hub_id takes presedence over a hub_name or default Hub.
        **hub_name(str): optional name of hub to operate on.
        **remote(bool): Remote or local query.
    """
    _fill_kwargs(kwargs)

    if device_exists(device_id, **kwargs):
        # blank out fields that don't make sense to set
        for key in ['lastSeen', 'reachable', 'maxTemperature', 'minTemperature']:
            state.pop(key, None)
        hub_api.devices_command_state(device_id=device_id, state=state, **kwargs)
    else:
        raise AttributeError('device {0} does not exist.'.format(device_id))


def device_on(device_id, **kwargs):
    """Turn on a device that is capable of turning on. Eligibility is determined by the capability ON_OFF.

    Args:
        device_id(str): ID of the device to operate on.
    """
    _fill_kwargs(kwargs)
    if device_eligible(device_id, capability.ON_OFF, **kwargs):
        hub_api.devices_command_on(device_id, **kwargs)
    else:
        raise ValueError('Device not found or not eligible for action.')


def device_off(device_id, **kwargs):
    """Turn off a device that is capable of turning off. Eligibility is determined by the capability ON_OFF.

    Args:
        device_id(str): ID of the device to operate on.
    """
    _fill_kwargs(kwargs)
    if device_eligible(device_id, capability.ON_OFF, **kwargs):
        hub_api.devices_command_off(device_id, **kwargs)
    else:
        raise ValueError('Device not found or not eligible for action.')


def light_temperature(device_id, temperature=2700, transition=0, **kwargs):
    """Set temperature of a light.

    Args:
        device_id(str): ID of the device to operate on.
        temperature(float): Temperature in Kelvins. If outside the operating range of the device the extreme value is used. Defaults to 2700K.
        transition(int): Transition length in milliseconds. Defaults to instant.
    """
    _fill_kwargs(kwargs)
    state = {}  # will be populated by device_eligible
    if device_eligible(
            device_id, capability.COLOR_TEMP, state=state, **kwargs) and _in_range(
                temperature,
                low=state['minTemperature'],
                high=state['maxTemperature'],
                description='Temperature'):

        state = _clean_state(state)
        state['colorMode'] = 'ct'
        state['temperature'] = temperature
        state['transitionMsec'] = transition
        hub_api.devices_command_state(device_id=device_id, state=state, **kwargs)
    else:
        raise ValueError('Device not found or not eligible for action.')


def light_color(device_id, hue, saturation=1.0, transition=0, **kwargs):
    """Set color (hue & saturation) of a light.

    Args:
        device_id(str): ID of the device to operate on.
        hue(float): Hue in the range of [0, Pi*2]. If outside the range a ValueError is raised.
        saturation(float): Saturation in the range of [0, 1]. If outside the range a ValueError is raised. Defaults to 1.0 (full saturation.)
        transition(int): Transition length in milliseconds. Defaults to instant.
    """
    _fill_kwargs(kwargs)
    state = {}  # will be populated by device_eligible
    if device_eligible(
            device_id, capability.COLOR_HS, state=state, **kwargs) and _in_range(
                hue, low=0.0, high=math.pi * 2, description='Hue') and _in_range(
                    saturation, low=0.0, high=1.0, description='Saturation'):

        state = _clean_state(state)
        state['colorMode'] = 'hs'
        state['hue'] = hue
        state['saturation'] = saturation
        hub_api.devices_command_state(device_id=device_id, state=state, **kwargs)
    else:
        raise ValueError('Device not found or not eligible for action.')


def light_brightness(device_id, brightness, transition=0, **kwargs):
    """Set brightness of a light.

    Args:
        device_id(str): ID of the device to operate on.
        brightness(float): Brightness in the range of [0, 1]. If outside the range a ValueError is raised.
        transition(int): Transition length in milliseconds. Defaults to instant.
    """
    _fill_kwargs(kwargs)
    state = {}  # will be populated by device_eligible
    if device_eligible(
            device_id, capability.BRIGHTNESS, state=state, **kwargs) and _in_range(
                brightness, low=0.0, high=1.0, description='Brightness'):

        state = _clean_state(state)
        state['brightness'] = brightness
        hub_api.devices_command_state(device_id=device_id, state=state, **kwargs)
    else:
        raise ValueError('Device not found or not eligible for action.')


### Hub modifiers ###


def remote(hub_id=None, new_state=None, commit=True):
    """Get remote status of hub or set a new value for it. Always returns current state at the end.

    Args:
        **hub_id(str): Id of hub to query. The id is a string of hexadecimal sections used internally to represent a hub. Defaults to hub.default()
        new_state(bool): New remoteness state to set for hub. True means remote. Defaults to None when only the current value will be returned.
        commit(bool): True to commit new state after set. Defaults to True.

    Returns:
        bool: True for a hub considered remote.
    """
    if hub_id is None:
        hub_id = default()
    if new_state is not None:
        if not isinstance(new_state, bool):
            raise ValueError('Expected boolean as new value of remote, got {0}'.format(
                type(new_state)))
        _setAttr(hub_id, 'remote', new_state, commit=commit)
    return _getAttr(hub_id, 'remote', default=False, boolean=True)


def autoremote(hub_id=None, new_state=None, commit=True):
    """Get autoremote status of hub or set a new value for it. Always returns current state at the end.

    Args:
        hub_id(str): Id of hub to query. The id is a string of hexadecimal sections used internally to represent a hub. Defaults to hub.default()
        new_state(bool): New autoremoteness state to set for hub. True means remote will be automanaged. Defaults to None when only the current value will be returned.
        commit(bool): True to commit new state after set. Defaults to True.

    Returns:
        bool: True for a hub with autoremote enabled.
    """
    if hub_id is None:
        hub_id = default()
    if new_state is not None:
        if not isinstance(new_state, bool):
            raise ValueError('Expected boolean as new value of autoremote, got {0}'.format(
                type(new_state)))
        _setAttr(hub_id, 'autoremote', new_state, commit=commit)
    return _getAttr(hub_id, 'autoremote', default=True, boolean=True)


### Hub info ###
def tz(**kwargs):
    """Get timezone of given hub or default hub if no id is specified. For more optional kwargs see cozify.hub_api.get()

    Args:
        **hub_id(str): Hub to query, by default the default hub is used.

    Returns:
        str: Timezone of the hub, for example: 'Europe/Helsinki'
    """
    _fill_kwargs(kwargs)

    return hub_api.tz(**kwargs)


def ping(autorefresh=True, **kwargs):
    """Perform a cheap API call to trigger any potential APIError and return boolean for success/failure. For optional kwargs see cozify.hub_api.get()

    Args:
        autorefresh(bool): Wether to perform a autorefresh after an initially failed ping. If successful, will still return True. Defaults to True.
        **hub_id(str): Hub to ping or default if neither id or name set.
        **hub_name(str): Hub to ping by name.

    Returns:
        bool: True for a valid and working hub authentication state.
    """
    try:
        _fill_kwargs(kwargs)  # this can raise an APIError if hub_token has expired
        # Detect remote-ness and flip state if needed
        if not kwargs['remote'] and kwargs['autoremote'] and not kwargs['host']:
            remote(hub_id=kwargs['hub_id'], new_state=True)
            kwargs['remote'] = True
            logging.debug('Ping determined hub is remote and flipped state to remote.')
        # We could still be remote but just have host set. If so, tz will fail.
        timezone = tz(**kwargs)
        logging.debug('Ping performed with tz call, response: {0}'.format(timezone))
    except APIError as e:
        refresh_codes = [401, 403]  # codes to consider for autorefresh
        fail_codes = [503, 504, 'connection failure']  # codes to consider a remote state failure
        if e.status_code in refresh_codes:
            if autorefresh:
                from cozify import cloud
                logging.warning('Hub token has expired, hub.ping() attempting to renew it.')
                logging.debug('Original APIError was: {0}'.format(e))
                if cloud.authenticate(trustHub=False):  # if this fails we let it fail.
                    return True
            logging.warning(e)
            return False
        elif e.status_code in fail_codes:
            if kwargs['autoremote']:
                remote(hub_id=kwargs['hub_id'], new_state=True)
                kwargs['remote'] = True
                logging.warning(
                    'Ping had connection issues to the hub and flipped to remote mode: {0}'.format(
                        e))
            else:
                logging.warning(e)
                return False
        else:  # unknown error code, raise it and let it burn
            raise
    else:
        return True


def name(hub_id=None):
    """Get hub name

    Args:
        hub_id(str): Id of hub to query. The id is a string of hexadecimal sections used internally to represent a hub.

    Returns:
        str: Hub name or None if the hub wasn't found.
    """
    if hub_id is None:
        hub_id = default()
    return _getAttr(hub_id, 'hubname')


def host(hub_id=None):
    """Get hostname of hub

    Args:
        hub_id(str): Id of hub to query. The id is a string of hexadecimal sections used internally to represent a hub.

    Returns:
        str: ip address of matching hub. Be aware that this may be empty if the hub is only known remotely and will still give you an ip address even if the hub is currently remote and an ip address was previously locally known.
    """
    if hub_id is None:
        hub_id = default()
    return _getAttr(hub_id, 'host')


def token(hub_id=None, new_token=None, commit=True):
    """Get hub_token or set a new value for it.

    Args:
        hub_id(str): Id of hub to query. The id is a string of hexadecimal sections used internally to represent a hub.
        commit(bool): True to commit new state after set. Defaults to True.

    Returns:
        str: Hub authentication token.
    """
    if hub_id is None:
        hub_id = default()
    if new_token:
        _setAttr(hub_id, 'hubtoken', new_token, commit=commit)
    return _getAttr(hub_id, 'hubtoken')


def hub_id(hub_name):
    """Get hub id by it's name.

    Args:
        hub_name(str): Name of hub to query. The name is given when registering a hub to an account.

    Returns:
        str: hub_id on success, raises an attributeerror on failure.
    """

    for section in config.state.sections():
        if section.startswith("Hubs."):
            logging.debug('Found hub: {0}'.format(section))
            if config.state[section]['hubname'] == hub_name:
                return section[5:]  # cut out "Hubs."
    raise AttributeError('Hub not found: {0}'.format(hub_name))


def exists(hub_id=None):
    """Check for existance of hub in local state.

    Args:
        hub_id(str): Id of hub to query. The id is a string of hexadecimal sections used internally to represent a hub.
    """
    if hub_id is None:
        hub_id = default()
    if 'Hubs.{0}'.format(hub_id) in config.state:
        return True
    else:
        return False


def default():
    """Return id of default Hub.

    If default hub isn't known an AttributeError will be raised.
    """

    if 'default' not in config.state['Hubs']:
        raise AttributeError(
            'Default hub not known, you should run cozify.authenticate(). Your current state is stored at: {0}'
            .format(config.state_path))
    else:
        return config.state['Hubs']['default']


### Internals ###


def _getAttr(hub_id, attr, default=None, boolean=False):
    """Get hub state attributes by attr name. Optionally set a default value if attribute not found.

    Args:
        hub_id(str): Id of hub to query. The id is a string of hexadecimal sections used internally to represent a hub.
        attr(str): Name of hub attribute to retrieve
        default: Optional default value to set for unset attributes. If no default is provided these raise an AttributeError.
        boolean: Retrieve and return value as a boolean instead of string. Defaults to False.
    Returns:
        str: Value of attribute or exception on failure.
    """
    section = 'Hubs.' + hub_id
    if section in config.state:
        if attr not in config.state[section]:
            if default is not None:
                _setAttr(hub_id, attr, default)
            else:
                raise AttributeError('Attribute {0} not set for hub {1}'.format(attr, hub_id))
        if boolean:
            return config.state.getboolean(section, attr)
        else:
            return config.state[section][attr]
    else:
        raise AttributeError("Hub id '{0}' not found in state.".format(hub_id))


def _setAttr(hub_id, attr, value, commit=True):
    """Set hub state attributes by hub_id and attr name

    Args:
        hub_id(str): Id of hub to store for. The id is a string of hexadecimal sections used internally to represent a hub.
        attr(str): Name of cloud state attribute to overwrite. Attribute will be created if it doesn't exist.
        value(str): Value to store
        commit(bool): True to commit state after set. Defaults to True.
    """
    if isinstance(value, bool):
        value = str(value)

    section = 'Hubs.' + hub_id
    if section in config.state:
        if attr not in config.state[section]:
            logging.info(
                "Attribute {0} was not already in {1} state, new attribute created.".format(
                    attr, section))
        config.state[section][attr] = value
        if commit:
            config.commit()
    else:
        logging.warning('Section {0} not found in state.'.format(section))
        raise AttributeError


def _get_id(**kwargs):
    """Get a hub_id from various sources, meant so that you can just throw kwargs at it and get a valid id.
    If no data is available to determine which hub was meant, will default to the default hub. If even that fails, will raise an AttributeError.

    Args:
        **hub_id(str): Will be returned as-is if defined.
        **hub_name(str): Name of hub.
    """
    if 'hub_id' in kwargs:
        return kwargs['hub_id']
    if 'hub_name' in kwargs:
        return hub_id(kwargs['hub_name'])
    return default()


def _fill_kwargs(kwargs):
    """Check that common items are present in kwargs and fill them if not.

    Args:
    kwargs(dict): kwargs dictionary to fill. Operated on directly.

    """
    if 'hub_id' not in kwargs:
        kwargs['hub_id'] = _get_id(**kwargs)
    if 'remote' not in kwargs:
        kwargs['remote'] = remote(hub_id=kwargs['hub_id'])
    if 'autoremote' not in kwargs:
        kwargs['autoremote'] = True
    if 'hub_token' not in kwargs:
        kwargs['hub_token'] = token(kwargs['hub_id'])
    if 'cloud_token' not in kwargs:
        from . import cloud
        kwargs['cloud_token'] = cloud.token()
    if 'host' not in kwargs:
        # This may end up being None if we're remote
        kwargs['host'] = host(kwargs['hub_id'])
    kwargs['filled'] = True


def _clean_state(state):
    """Return purged state of values so only wanted values can be modified.

    Args:
    state(dict): device state dictionary. Original won't be modified.
    """
    out = {}
    for k, v in state.items():
        if isinstance(v, dict):  # recurse nested dicts
            out[k] = _clean_state(v)
        elif k == "type":  # type values are kept
            out[k] = v
        else:  # null out the rest
            out[k] = None
    return out


def _in_range(value, low, high, description='undefined'):
    """Check that the value is in the given range, raise an error if not.
    None is always considered a valid value.

    Returns:
        bool: True if value in range. Otherwise a ValueError is raised.
    """
    if value is not None and (value < low or value > high):
        raise ValueError('Value({3}) \'{0}\' is out of bounds: [{1}, {2}]'.format(
            value, low, high, description))
    else:
        return True
