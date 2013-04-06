import thread
from time import sleep

from serial_connection import *
from linear_slides import *
from rotary_stages import *
from scancam import *

import idscam.common.syslogger

log = idscam.common.syslogger.get_syslogger('scancam_tester')

log.warning("warning log")
log.info("info log")
log.critical("critical log")
log.debug("debug log")

WAIT_TIME = 100


ser = serial_connection('/dev/ttyUSB0')


try:
    # for x_stage (T-LSM200A)
    x_stage = linear_slide(ser, 1, mm_per_rev = .6096, verbose = True, run_mode = STEP)

    # for theta rotary stage (
    theta_stage = rotary_stage(ser, 2, deg_per_step = .015, verbose = True, run_mode = STEP)

    # for z_stage    (LSA10A-T4) 
    #z_stage = linear_slide(ser, 3, mm_per_rev = .3048, verbose = True, run_mode = STEP)

    # Start thread for serial commnunication
    thread.start_new_thread( ser.open, ())

    camera = ueye_camera(cam_device_id = 1, verbose = True) 

    scancam = xthetaz_scancam( [x_stage, theta_stage], camera )

    scancam.home()

    scancam.move({'x':75, 'y':30}, False)

    scancam.wait_for_stages_to_complete_actions(100)

    print "Done with move"
    
except KeyboardInterrupt:
    scancam.stop()
        

finally:            
    # Close serial connection before final exit
    print "Closing serial connection"
    ser.close()
    print "Connection closed"









