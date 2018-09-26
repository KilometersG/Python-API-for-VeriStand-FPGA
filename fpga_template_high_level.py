import fpga_config

configpath = input('Please enter the full filepath of your .fpgaconfig file: ')
vsfpga = fpga_config.VeriStandFPGA(configpath)
device = input('Please enter the device name of your FPGA as it appears in NI-MAX: ')

print('Please input five values separated by commas for the following channels')
print('Please enter PWMs as 0-100 Duty Cycles, Digital Lines as 1\'s or 0\'s and Analog Lines as floating points')
iteration_writes = {}
for write_packet in vsfpga.write_packet_list:
    for channel in write_packet:
        valuestr = input('{}: '.format(channel['name']))
        channel_values = valuestr.split(',')
        for k, value in enumerate(channel_values):
            iteration_writes['{},{}'.format(channel['name'], k)] = int(value)

while True:
    loop_rate = input("Please enter desired FPGA loop rate in ms: ")
    try:
        vsfpga.init_fpga(device, int(loop_rate))
    except ValueError:
        print('FPGA loop rate must be an integer')
    else:
        break

vsfpga.start_fpga()

for i in range(5):
    vsfpga.vs_read_fifo(timeout=2000)
    print('Iteration {} values are: '.format(i))
    for current_read_packet in vsfpga.read_packet_list:
        for read_channel in current_read_packet:
            channel_name = read_channel['name']
            print('{}: {}'.format(channel_name, vsfpga.get_channel(channel_name)))
    for current_write_packet in vsfpga.write_packet_list:
        for write_channel in current_write_packet:
            vsfpga.set_channel(channel_name=write_channel['name'],
                               value=iteration_writes['{},{}'.format(write_channel['name'], i)])
    vsfpga.vs_write_fifo(timeout=2000)
vsfpga.stop_fpga()
