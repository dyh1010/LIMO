builtin_interfaces/Time stamp

string STATE_INITIALIZING=INITIALIZING
string STATE_READY=READY
string STATE_EXECUTING=EXECUTING
string STATE_STOPPING=STOPPING
string STATE_FAULT_LATCHED=FAULT_LATCHED
string STATE_CLOSED=CLOSED

string gateway_state
bool valid
bool physical_stop_required
string session_id
uint64 sample_sequence
string port
string usb_vid_pid
string usb_serial

int8 controller_connected
int8 power_on
int8 moving
int8 paused
int32 error_code
int8 fresh_mode
int8 all_servos_enabled

float64[6] joint_angles_deg
float64[6] tcp_pose

string active_command_id
string fault_reason
