from warnings import warn
from serial_connection import *
from Queue import Queue
from time import sleep
import signal

CONTINUOUS, STEP = (0,1)




# Command format:
# 'command_name': command
base_commands = {
        'reset':                    0,
        'home':                     1,
        'renumber':                 2 ,
        'store_current_position':   16,
        'return_stored_position':   17,
        'read_or_write_memory':     35,
        'restore_settings':         36,
        'return_setting':           53,
        'echo_data':                55,
        'return_current_position':  60,
        }

move_commands = {
        'stored_position':          18,
        'absolute':                 20,
        'relative':                 21,
        'constant_speed':           22,
        'stop':                     23,
        }

setting_commands = {
        'microstep_resolution':     37,
        'running_current':          38,
        'hold_current':             39,
        'device_mode':              40,
        'target_speed':             42,
        'acceleration':             43,
        'maximum_range':            44,
        'current_position':         45,
#        'max_relative_move':        46,  Commented out due to incompatibility with A-MCA
        'home_offset':              47,
        'alias_number':             48,
#        'lock_state':               49,  Commented out due to incompatibility with A-MCA
        }

extra_error_codes = {
        'busy':                      255,
        'save_position_invalid':    1600,
        'save_position_not_homed':  1601,
        'return_position_invalid':  1700,
        'move_position_invalid':    1800,
        'move_position_not_homed':  1801,
        'relative_position_limited':2146,
        'settings_locked':          3600,
        'disable_auto_home_invalid':4008,
        'bit_10_invalid':           4010,
        'home_switch_invalid':      4012,
        'bit_13_invalid':           4013,
        }

meta_commands = {}

class device_base():
    ''' device_base(connection, id, run_mode = CONTINUOUS, verbose = False)

    Implements the device base class. It doesn't do very much by itself.

    connection: Should be an instance of the serial_connection class.
    
    id: A user-defined string for this device. If no id is passed then 
        a string representation of the hash of this instance is used

    run_mode: Defines whether the device should run through every queue that gets placed
        on the command queue, or whether it should do one at a time and wait for step()
        to be called before running the next. The options are CONTINUOUS (the former mode)
        and STEP (the latter mode).
    
    verbose: Boolean representing whether to be verbose or not.
    '''

    def __init__(self, 
                 connection, 
                 id = None,
                 run_mode = CONTINUOUS,
                 verbose = False):

        # These have to be initialised immediately to prevent a potential infinite
        # recursion when the attribute handler can't find them.
        self.base_commands = {}
        self.meta_commands = {}
        self.user_meta_commands = {}
        self.setting_commands = {}
        self.move_commands = {}
        
        if id == None:
            id = str(hash(self))
        
        self.id = id
        self.connection = connection

        self.run_mode = run_mode
        
        self.awaiting_action = False
        self.last_packet_received = None
        self.last_packet_sent = None
        
        self.meta_command_depth = 0
        self.meta_command_pause_after = False
        self.pause_after = True

        # Register with the connection
        self.connection.register(self.packet_handler, id)
        
        self.base_commands = {}
        self.meta_commands = {}
        self.user_meta_commands = {}

        self.setting_commands = {}
        self.move_commands = {}
        
        self.action_state = False

        self.pending_responses = 0

        self.verbose = verbose

        # Create data structures to store the response lookups
        self.settings_lookup = {}
        self.command_lookup = {}
        self.move_lookup = {}
        self.extra_error_codes_lookup = {}

    def __getattr__(self, attr):
        
        if self.base_commands.has_key(attr):
            def base_function(data = 0):
                return self.enqueue_base_command(attr, data)

            return base_function

        elif attr[0:5] == 'move_' and self.move_commands.has_key(attr[5:]):
            def move_function(data = 0):
                return self.move(attr[5:], data)

            return move_function 
        
        elif attr[0:4] == 'set_' and self.setting_commands.has_key(attr[4:]):
            def set_function(data = 0):
                return self.set(attr[4:], data)

            return set_function

        elif attr[0:4] == 'get_' and self.setting_commands.has_key(attr[4:]):
            def get_function(blocking = False):
                return self.get(attr[4:], blocking = blocking)

            return get_function

        elif self.meta_commands.has_key(attr):
            def do_function(data = 0):
                return self.meta(attr, self.meta_commands[attr])

            return do_function
        
        elif self.user_meta_commands.has_key(attr):
            def do_function(data = 0):
                return self.meta(attr, self.user_meta_commands[attr])

            return do_function

        else:
            raise AttributeError

        return None
    
    def get_id(self):
        ''' devive_base.get_id()

        Return the ID that this device has been assigned
        '''
        return self.id

    def step(self):
        '''device_base.step()

        This function executes the next command in the command queue.

        It blocks if the previous command has not finished and returns
        when it has and the next command has been sent.

        This function operates by pulling packets off the queue until
        we are in a position to execute the next command.
        '''
        self.awaiting_action = False
        
        if len(self.command_queue) == 0:
            # Nothing to do here cos there's nothing on the queue.
            if self.verbose:
                print 'Command queue empty for receive step command'
        elif self.in_action() and self.run_mode == STEP \
                and not self.connection.running.isSet():
            # Device is in the action state and the queue handler isn't running,
            # so we need to manually pull a packet off the queue 
            # (which will block until something is there)
            self.connection.queue_handler(1)
        elif self.in_action() and self.run_mode == STEP:
            # We need to do something when we're no longer in action
            # so notify the packet handler of this
            self.awaiting_action = True
        elif not self.in_action():
            # We should send the command now
            apply(self.do_now, self.command_queue.pop(0))
        elif self.run_mode == CONTINUOUS:
            # This is the state when we are in_action() but 
            # the queue handler should make things
            # work nicely when the time comes.
            pass

        return None


    def enqueue(self, command, data = 0, command_dictionary = None, pause_after = True):
        '''device_base.enqueue(command, data = 0, command_dictionary = None)

        enqueue a command for subsequent execution. If the queue is empty, the
        command is immediately executed.

        command should be a reference to an entry in command_dictionary. The default
        command dictionary is base_commands and is used if command_dictionary == None.

        data is the data that should be passed at execution.
        '''

        if command_dictionary == None:
            command_dictionary = self.base_commands
        
        if self.meta_command_depth > 0 and not self.meta_command_pause_after:
            pause_after = False
        else:
            if self.verbose:
                for n in range(0,self.meta_command_depth):
                    print '\t',
                print 'pause'


        if not self.in_action() and len(self.command_queue) == 0 and not self.responses_pending()\
            and not self.run_mode == STEP:
            # Execute immediately
            apply(self.do_now, (command_dictionary[command], data, pause_after))
        else:
            self.command_queue.append((command_dictionary[command], data, pause_after))

        return None
    
    def enqueue_base_command(self, command, argument):
        '''device_base.base_command(command, argument)

        Called when a base command is to be dealt with.
        Just enqueues the command.
        '''
        if self.verbose:
            for n in range(0,self.meta_command_depth):
                print '\t',

            print 'enqueuing: %s, %s (%i): %i' % \
                    (self.id, command, self.base_commands[command], argument)

        self.enqueue(command, argument, self.base_commands)

    def on_base_command_error(self, error):
        ''' device_base.on_base_command_error(error)

        This is the base command error handling function.

        This function will just print out that an error was received and
        then blithely move on.
        '''
        if error > 1000:
            print 'error   : %s' % self.extra_error_codes_lookup[error]
        elif self.base_commands.has_key(error):
            print 'error   : invalid %s' % self.base_commands[error]
        else:
            print 'error   : unknown device error, zaber code: %s' % str(error)

        return None
    
    def get(self, setting, blocking = False):
        ''' device_base.get(setting, blocking = False)
        
        Exit quietly. This attribute should be overwritten in child classes.

        Any calls to self.get_SOMETHING end up here with the setting string
        SOMETHING.
        '''
        return None

    def set(self, setting, value):
        ''' device_base.set(setting, value)
        
        Exit quietly. This attribute should be overwritten in child classes.

        Any calls to self.set_SOMETHING end up here with the setting string
        SOMETHING.
        '''

        return None

    def on_settings_error(self, error):
        ''' device_base.on_settings_error(error)

        This is the settings error handling function.

        This function will just print out that an error was received and
        then blithely move on.
        '''
        if error > 1000:
            print 'error   : %s' % self.extra_error_codes_lookup[error]
        else:
            print 'error   : invalid %s' % self.setting_commands[error]

        return None

    def move(self, move_command, argument):
        ''' device_base.move(move_command, argument)
        
        Exit quietly. This attribute should be overwritten in child classes.

        Any calls to self.move_SOMETHING end up here with the move_command string
        SOMETHING.
        '''

        return None
    
    def on_move_error(self, error):
        ''' device_base.on_move_error(error)

        This is the move error handling function.

        This function will just print out that an error was received and
        then blithely move on.
        '''
        if error > 1000:
            print 'error   : %s' % self.extra_error_codes_lookup[error]
        else:
            print 'error   : invalid %s' % self.move_commands[error]

        return None

    def on_busy_error(self):
        '''device_base.on_busy_error()

        This function resends the last command until it goes through.
        '''
        print 'error   : Busy error received, resending the last command'
        
        self.do_now(self.last_packet_sent[1], self.last_packet_sent[2])


    def meta(self, name, meta_command):
        '''device_base.meta(meta_command)

        Execute the supplied meta command. At this stage it is
        expanded out and the relevant functions are called to handle it.

        meta commands that are part of the meta_command recursively
        call this function.
        '''
        
        if self.verbose:
            for n in range(0,self.meta_command_depth):
                print '\t',
            print 'metacommand: %s' % (name)

        self.meta_command_depth = self.meta_command_depth + 1

        last_command = None
        
        for idx in range(0,len(meta_command)):
            each_command = meta_command[idx]
            
            if idx+1 < len(meta_command) and meta_command[idx+1][0] == 'pause':
                next_command_pause = True
            else:
                next_command_pause = False

            if each_command[0] == 'pause':
                # We considered pause on the last loop
                continue

            elif self.base_commands.has_key(each_command[0]) or \
                   self.move_commands.has_key(each_command[0][5:]) or \
                   self.meta_commands.has_key(each_command[0]) or \
                   self.user_meta_commands.has_key(each_command[0]):

                if next_command_pause:
                    self.meta_command_pause_after = True
                else:
                    self.meta_command_pause_after = False
                
                apply(getattr(self,each_command[0]), each_command[1:])
                last_command = each_command
            elif each_command[0] == 'repeat':
                # Special case of repeat

                if not last_command == None:
                    n = 0
                    if len(each_command) == 1:
                        # ie, no argument sent
                        iterations = 1
                    else:
                        iterations = each_command[1] - 1
                    
                    while n < iterations:
                        if n == iterations - 1 and next_command_pause == True:
                            self.meta_command_pause_after = True

                        apply(getattr(self,last_command[0]), last_command[1:])
                        n = n+1
        
        self.meta_command_pause_after = False
        self.meta_command_depth = self.meta_command_depth - 1
        return None
                

    def new_meta_command(self, name, command_list):
        ''' device_base.new_meta_command(name, command_list)
        
        Define a new meta command (a command sequence) that can then
        be called like an existing command.

        This function allows the special command 'repeat', with an argument
        as the number of times to repeat.

        A meta command can consist of move commands, base commands and
        other meta commands, as well as repeats.

        command_list should be a tuple of commands, with each command itself
        a tuple, of the form (command, argument)
        '''
        
        
    
        # Check that all the commands are valid.
        for each_command in command_list:
            if not self.base_commands.has_key(each_command[0]) and \
               not self.move_commands.has_key(each_command[0][5:]) and \
               not self.meta_commands.has_key(each_command[0]) and \
               not self.user_meta_commands.has_key(each_command[0]) and \
               not each_command[0] == 'repeat' and \
               not each_command[0] == 'pause':
                
                raise LookupError, 'Command in the supplied command list that is not valid'
                return None

        self.user_meta_commands[name] = command_list
        return None

    def do_now(self, command, data = None, pause_after = True, 
            blocking = False, release_command = None):
        ''' device_base.do_now(command, data = None, pause_after = True, 
                    blocking = False, release_command = None)
            
        Place holder function that should be overwritten in child classes.
        
        This function is called when a packet is wanted to be sent immediately 
        to the device.
        '''

        return None

    def get_all_settings(self, blocking = False):
        '''device_base.get_all_settings(blocking = False)

        Iterate over all the settings in self.setting_commands and call 
        self.get(setting, blocking) for each setting.
        '''
        for each_setting in self.setting_commands:
            self.get(each_setting, blocking=blocking)

        return None

    def in_action(self):
        '''device_base.in_action()

        Return the action state of the current device. This is fairly loosely
        defined and is dependant on the class implementation. It is basically
        used as a test as to whether the next command in the queue should be sent.
        '''
        return self.action_state

    def responses_pending(self):
        '''device_base.responses_pending()

        Return whether we are still awaiting a packet from the device.
        '''
        return self.pending_responses > 0

    def handle_device_packet(self, source, command, data):
        '''device_base.handle_device_packets(source, command, data)

        Place holder function that should be overwritten in child classes.
        
        This function should handle a packet that originated at the device
        with the id given by source. command is normally an echo of the 
        sent command with data being whatever the response is.
        '''
        return None

    def handle_general_packet(self, source, data):
        '''device_base.handle_general_packet(source, data)

        Any general packets put on the device queue destined for the device
        id assigned to this device end up here.

        All packets are assumed to be command packets and are interpreted as 
        such. The data packet is assumed to be of the following form:
        ('method', argument1, argument2, ...)

        All methods defined in the instance of the class are available to be
        called in this way. Any value returned from the method is placed on the
        queue with "source" as the destination (ie, replies are sent back).
        '''
        
        try: 
            reply = apply(getattr(self,data[0]), data[1:])
        
            if not reply == None:
                self.connection.packet_q.put(((self.id, source),(reply)))
        except:
            if self.verbose:
                print 'Packet received from %s for which nothing can be done: %s' % \
                        (source, str(data))

    def packet_handler(self, packet):
        '''device_base.packet_handler(packet)

        Interpret packets that have been placed on the queue and destined for this
        class instance.

        It attempts to interpret whether we have a device packet (a packet originating
        at the device) or a general packet (anything other data placed on the queue).

        It then dispatches the packet to the either self.handle_device_packet() or
        self.handle_general_packet()
        '''
        if len(packet) == 2:
            # We have a usual packet
            try:
                source = packet[0][0]
                destination = packet[0][1]
                data = packet[1]
                if not destination == self.id:
                    raise StandardError

            except:
                warn('Malformed packet received. Ignoring it...')
                return -1
            
            self.handle_general_packet(source, data)
        else:
            try:
                source = packet[0]
                command = packet[1]
                data = packet[2]
            except:
                warn('Malformed device packet received. Ignoring it...')
                return -1
            
            self.handle_device_packet(source, command, data) 


    class DeviceTimeoutError(Exception):
        def __init__(self, device_id):
            self.device_id = device_id
        def __str__(self):
            return repr(self.device_id)



    def wait_for_action_to_complete(self, timeout_secs):
        '''wait_for_actions_to_complete(devices, timeout_secs)

        Wake up once a second to see if current action has completed

        Raises self.DeviceTimeoutError exception after waiting for timeout_secs
        seconds without self.in_action() returning false.
        '''
            
        counter = 0
        while (1):
            sleep(1)
            counter += 1

            if not self.in_action():
                break

            if counter >= timeout_secs:
                    print self.id, "timeout after %d secs" % counter
                    raise self.DeviceTimeoutError( self.id )



class zaber_device(device_base):
    ''' zaber_device(connection, 
                     device_number, 
                     id,
                     units_per_step = None,
                     move_units = 'microsteps',
                     run_mode = CONTINUOUS,
                     action_handler = None,
                     verbose = False)
    
    Class to handle the general Zaber devices. The class talks to the device
    over an instance of the serial_connection class passed as connection.

    id: A user defined string that is used as the identifier for this class instance.
        It is used to allow a more human readable reference to the device in question.

    device_number: This is the number that identifies the Zaber device on the serial chain.

    units_per_step: This is the how many "units" correspond to one step of the stepper motor.

    move_units: A string identifier for the current unit. The default is microsteps. One 
        microstep is a quantity defined by the device and is found at initialisation.
    
    run_mode: Defines whether the device should run through every queue that gets placed
         on the command queue, or whether it should do one at a time and wait for step()
         to be called before running the next. The options are CONTINUOUS (the former mode)
         and STEP (the latter mode).

    action_handler: This is the function that is called when the device is ready for its
        next action. 
 
    verbose: A boolean flag to define the verbosity of the output.
    '''

    def __init__(self, 
                 connection, 
                 device_number, 
                 id = None,
                 units_per_step = None,
                 move_units = 'microsteps',
                 run_mode = CONTINUOUS,
                 action_handler = None,
                 verbose = False):
        
        # These have to be initialised immediately to prevent a potential infinite
        # recursion when the attribute handler can't find them.
        self.base_commands = base_commands
        self.move_commands = move_commands
        self.meta_commands = {}
        self.user_meta_commands = {}
        self.setting_commands = setting_commands       
        
        self.action_handler = action_handler 

        # Define move units if not already done
        try: self.move_units
        except AttributeError:
            self.move_units = move_units
        
        if units_per_step == None:
            # If units_per_step has not been defined, then we
            # have to work with microsteps and ignore any predefined units
            self.move_units = 'microsteps'
        
        self.units_per_step = units_per_step

        self.initialised = False

        self.device_number = device_number
        
        device_base.__init__(self, connection, id, run_mode = run_mode, verbose = verbose)
        
        self.connection.register_device(self.id, self.device_number)

        self.base_commands = base_commands
        self.move_commands = move_commands
        self.extra_error_codes = extra_error_codes
        self.meta_commands = {}
        self.user_meta_commands = {}

        self.setting_commands = setting_commands

        self.command_queue = []
        
        self.last_command = None
        self.error_list = []
        self.blocking_retries = 3

        # Fill the data structures to store the response lookups
        for each_setting in self.setting_commands:
            self.settings_lookup[self.setting_commands[each_setting]] = each_setting
        
        for each_command in self.base_commands:
            self.command_lookup[self.base_commands[each_command]] = each_command
    
        for each_movement in self.move_commands:
            self.move_lookup[self.move_commands[each_movement]] = each_movement
       
        for each_error_code in self.extra_error_codes:
            self.extra_error_codes_lookup[self.extra_error_codes[each_error_code]] = \
                    each_error_code
        
        # Define a safe initialisation value of the usteps/unit
        self.microsteps_per_unit = 0

        # Initialisation has occurred when we have all the settings returned
        # from the device
        self.settings = {}
        self.get_all_settings(blocking = True)

    def get(self, setting, blocking = False):
        ''' zaber_device.get(setting, blocking = False)

        Query the zaber device for the setting given by the setting string.
        
        See the setting_commands dictionary or consult the zaber documentation
        for valid settings.

        As with all device commands, this is returned asynchronously and so the return
        case should be handled properly by the device packet handler.

        It is possible to call this function with the blocking argument set to
        true. In this case, responses will be popped off the queue one by one
        (and dealt with appropriately) until the setting response arrives back,
        at which point normal execution will resume. In this case, the function will
        return the setting.

        Any calls to self.get_SOMETHING end up here with the setting string
        SOMETHING.
        '''
        
        if blocking:
            # Firstly we need to know how many errors are already on the
            # error list
            preexisting_errors = self.error_list.count(setting)
        
        attempt = 1
        while (not blocking and attempt == 1) or \
                (blocking and attempt < self.blocking_retries):
            # If we are blocking, keep trying until we don't
            # receive an error up to self.blocking_retries times
            self.do_now(self.base_commands['return_setting'],\
                    self.setting_commands[setting], blocking = blocking,\
                    release_command = setting)

            # See if we have received a satisfactory response and leave when we do            
            if self.error_list.count(setting) == preexisting_errors:
                return self.settings[setting]
            else:
                self.error_list.remove(command)
                attempt = attempt + 1

        return None

    def set(self, setting, value):
        ''' zaber_device.set(setting, value)

        Set the device setting given by the setting string with 'value'.

        See the setting_commands dictionary or consult the zaber documentation
        for valid settings.
        
        Any calls to self.set_SOMETHING end up here with the setting string
        SOMETHING.
        '''

        self.do_now(self.setting_commands[setting], value)
        return None

    def move(self, move_command, argument):
        ''' zaber_device.move(move_command, argument)

        Move the device using the command move_command with the supplied argument.

        Valid move commands are given in self.move_commands.

        Any calls to self.move_SOMETHING() end up here with the move_command string
        SOMETHING.
        '''

        if move_command == 'stored_position':
            if self.verbose:
                for n in range(0,self.meta_command_depth):
                    print '\t',

                print 'enqueuing: %s, move %s (%i): address %i' % \
                        (self.id, move_command, \
                        self.move_commands[move_command], data)
           
            self.enqueue(move_command, argument, self.move_commands)
        else:
            if self.verbose:
                for n in range(0,self.meta_command_depth):
                    print '\t',
                print 'enqueuing: %s, move %s (%i): %i %s' % \
                        (self.id, move_command, self.move_commands[move_command],\
                        argument, self.move_units)

            microstep_movement = int(float(argument) * self.microsteps_per_unit)
            
            self.enqueue(move_command, microstep_movement, self.move_commands)
            
        return None
    
    def do_now(self, command, data = None, pause_after = True, 
            blocking = False, release_command = None):
        '''zaber_device.do_now(command, data = None, pause_after = True,
            blocking = False, release_command = None)

        Send the device the command given by command with the supplied data.

        If no data is given, then 0 is sent.

        The paused flag tells the function whether this command should raise
        the self.pause_after flag. This is only maintained until the next packet is
        sent, at which point it is preempted by the next packet. The
        self.pause_after flag tells the action_handler to pause after execution
        of this command. The next command is initiated with the step() method.
        CONTINUOUS mode is equivalent to pause_after always equal to false. By
        default, every command will cause a pause.

        If the blocking flag is set to True, then this function will not
        return until release_command gets put on the queue
        or we run out of pending responses (probably implying an error occurred).

        If release_command is not passed or is None, then then command is used
        as the release command (ie an echo is expected)
        '''
        if data == None:
            data = 0

        if release_command == None:
            release_command = command

        self.pause_after = pause_after

        command_tuple = (self.device_number, command, data)

        apply(self.connection.send_command, command_tuple)
        
        if self.in_action() and self.move_lookup.has_key(command):
            # This means the current command will preempt a previously sent command,
            # so we shouldn't do anything.
            if self.verbose:
                print "send:      %s, move %s (%i): %i" \
                            %(self.id, self.move_lookup[command], command, data)

        elif self.command_lookup.has_key(command):
            # if its not a base command, we trigger the action state
            self.action_state = True
            self.pending_responses = self.pending_responses + 1
            self.last_action_sent = self.command_lookup.has_key(command)
            if self.verbose:
                print "send:      %s, command %s (%i): %i" \
                        %(self.id, self.command_lookup[command], command, data)

        elif self.move_lookup.has_key(command):
            # if its not a move command, we trigger the action state
            self.action_state = True
            self.pending_responses = self.pending_responses + 1
            self.last_action_sent = self.move_lookup.has_key(command)
            if self.verbose:
                print "send:      %s, move %s (%i): %i" \
                        %(self.id, self.move_lookup[command], command, data)

        elif  self.settings_lookup.has_key(command):
            # Its a settings command
            self.pending_responses = self.pending_responses + 1

        else:
            # Don't know what to do with this...
            pass
        
        # If the blocking request was made, we take control of the
        # queue handler until our packet arrives. All other packets
        # arrive as usual and are handled in the same way. That is, 
        # the queue handler will do its usual thing, dispatching
        # packets, only it will be one at a time, initiated by this
        # loop. We drop out of the loop when a response is received for
        # the command we sent or no more responses are expected.
        if blocking:
            last_packet_sent_temp = self.last_packet_sent
            self.last_packet_sent = command_tuple
            while self.last_packet_received == None or \
                    not self.last_packet_received[1] == release_command:
                if self.responses_pending():
                    self.connection.queue_handler(1)
                else:
                    self.error_list.append(command)
                    break
            
            self.last_packet_sent = last_packet_sent_temp
        else:
            self.last_packet_sent = command_tuple
        
        return None

    def handle_device_packet(self, source, command, data):
        '''zaber_device.handle_device_packet(source, command, data)

        Handle a device packet that is received.

        Currently the function can only handle packets that are in the
        dictionaries: self.command_lookup, self.move_lookup and 
        self.settings_lookup.

        Command or move packets will trigger an action response, which is to call
        the action_handler function.
        
        TODO:   implement handling of the rest of the command set
        '''
        
        if command == 255:
            # We have received an error            
            if data == 255:
                # This means the device was busy during the last request
                self.pending_responses = self.pending_responses - 1
                if not self.responses_pending():
                    self.action_state = False
                self.on_busy_error()
            
            elif  self.command_lookup.has_key(data) \
                    or self.command_lookup.has_key(int(data/100)):
                self.pending_responses = self.pending_responses - 1
                
                self.on_base_command_error(data)
            
            elif self.move_lookup.has_key(data) \
                    or self.move_lookup.has_key(int(data/100)):
                self.pending_responses = self.pending_responses - 1

                self.on_move_error(data)

            elif self.settings_lookup.has_key(data) \
                    or self.settings_lookup.has_key(int(data/100)):
                self.pending_responses = self.pending_responses - 1
                
                self.on_settings_error(data)

        elif self.command_lookup.has_key(command):
            self.pending_responses = self.pending_responses - 1
            
            if self.verbose:
                print 'received:  %s, command %s (%i): %i' \
                        %(self.id, self.command_lookup[command], command, data)

        elif self.move_lookup.has_key(command):
            self.pending_responses = self.pending_responses - 1

            if self.verbose:
                print 'received:  %s, moved %s (%i): %i' \
                        %(self.id, self.move_lookup[command], command, data)

        elif self.settings_lookup.has_key(command):
            self.pending_responses = self.pending_responses - 1

            if self.verbose:
                print 'received:  %s, %s set (%i): %i' \
                        %(self.id, self.settings_lookup[command], command, data)
             
            self.settings[self.settings_lookup[command]] = data
            
            if self.settings_lookup[command] == 'microstep_resolution':
                if not self.move_units == 'microsteps':
                    self.microsteps_per_unit = float(data)/self.units_per_step
                else:
                    self.microsteps_per_unit = 1
            
            if len(self.settings) == len(self.settings_lookup):
                self.initialised = True
        
        else:
            # Ignore packets that we don't know how to handle
            # But still print out that we received them...
            if self.verbose:
                print 'received:  %s, %i: %i' \
                        %(self.id, command, data)
            return None

        if not self.responses_pending():
            self.action_state = False
        
        if (self.command_lookup.has_key(command) or self.move_lookup.has_key(command)):
            # If we have an action (rather than a setting) then pass over to the
            # action handler
            self.handle_action(source, command, data, self.pause_after)

        self.last_packet_received = (source, command, data)

    def handle_action(self, source, command, data, pause_after):
        if self.run_mode == STEP and \
                pause_after and \
                not self.awaiting_action:
            pass
        else:    
            if self.action_handler == None:
                self.step()
            else:
                self.action_handler(source, command, data, pause_after)

        return None

def zaber_device_example(io):
    
    device_1 = zaber_device(io, 1, 'device_1', verbose = True)
    device_2 = zaber_device(io, 2, 'device_2', verbose = True)
    
    device_1.home()
    device_2.home()
    
    device_1.move_relative(10000)
    device_2.move_absolute(200000)
    device_2.home()
    device_1.move_absolute(100000)
    device_2.move_absolute(80000)
    
    # Will block
    io.open()

def step_example(io):

    try:
        device_1 = zaber_device(io, 1, 'device_1', run_mode = STEP, verbose = True)
        device_2 = zaber_device(io, 2, 'device_2', run_mode = STEP, verbose = True)
        
        device_1.home()
        device_2.home()
        
        device_1.move_relative(10000)
        device_2.move_absolute(200000)
        device_2.home()
        device_1.move_absolute(100000)
        device_2.move_absolute(80000)
        
        while len(device_1.command_queue) > 0:
            device_1.step()

        while len(device_2.command_queue) > 0:
            print 'foo'
            device_2.step()
    
    except KeyboardInterrupt:
        pass

    io.close()

def examples(argv):
    '''A short example program that moves stuff around
    '''
    io = serial_connection('/dev/ttyUSB0', '<2Bi')
    #zaber_device_example(io)
    step_example(io)

if __name__ == "__main__":
    import sys
    examples(sys.argv)
