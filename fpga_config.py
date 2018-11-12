import xml.etree.ElementTree as ET
from nifpga import Session
import ntpath


class VeriStandError(Exception):
    """
    Base class for exceptions in this API
    """
    pass


class ConfigError(VeriStandError):
    """
    Exception raised for errors in the .fpgaconfig file

    Attributes
        message = explanation of error.
    """
    def __init__(self, message):
        self.message = message


class PacketError(VeriStandError):
    """
    Exception raised for errors in a packet

    Attributes
        Message -- explanation of error
        packetID -- packet number and direction that the error occurred in.
    """
    def __init__(self, message, packetID):
        self.message = message
        self.packetID = packetID


class VeriStandFPGA(object):
    """
    DMA FIFO info pulled from an .fpgaconfig file
    config_file is the file name of the XML that defines this FIFO
    Direction is a string stating read or write. 

    """

    def __init__(self, filepath):
        """
        Create a fpga_config object. The filepath is the path to the bitfile you wish to interact with.
        This creates the fpga configuration with a number of read and write packets.
        :param filepath:
        """
        self.filepath = filepath
        self.tree = ET.parse(self.filepath)
        self.root = self.tree.getroot()
        self.read_packets = None
        self.write_packets = None
        self.session = None
        self.write_fifo_object = None
        self.read_fifo_object = None
        for child in self.root:
            if child.tag == 'DMA_Read':
                self.read_packets = int(child[0].text)
                self.read_fifo_tag = child
            elif child.tag == 'DMA_Write':
                self.write_packets = int(child[0].text)
                self.write_fifo_tag = child
            elif child.tag == 'Bitfile':
                self.bitfile = child.text
        self.folder = ntpath.split(self.filepath)
        self.full_bitpath = self.folder[0] + '\\{}'.format(self.bitfile)
        if self.read_packets is None:
            raise ConfigError(message='No DMA_Read tag present')
        elif self.write_packets is None:
            raise ConfigError(message='No DMA_Write tag present')
        self.read_packet_list = []
        self.write_packet_list = []
        self.channel_value_table = {}
        for pack_index in range(self.read_packets):
            self.read_packet_list.append(self._create_packet('read', pack_index + 1))
            for chan_index in range(self.read_packet_list[pack_index].definition['channel_count']):
                self.channel_value_table[self.read_packet_list[pack_index].definition['name{}'.format(chan_index)]] = 0
        for pack_index in range(self.write_packets):
            self.write_packet_list.append(self._create_packet('write', pack_index + 1))
            for chan_index in range(self.write_packet_list[pack_index].definition['channel_count']):
                self.channel_value_table[self.write_packet_list[pack_index].definition['name{}'.format(chan_index)]] = 0

    def init_fpga(self, device, loop_rate):
        self.session = Session(self.full_bitpath, device, reset_if_last_session_on_exit=True)
        self.session.download()
        self.session.run()
        print(self.session.fpga_vi_state)
        self.write_fifo_object = self.session.fifos['DMA_WRITE']
        self.read_fifo_object = self.session.fifos['DMA_READ']
        self.loop_timer = self.session.registers['Loop Rate (usec)']
        self.fpga_start_control = self.session.registers['Start']
        self.fpga_rtsi = self.session.registers['Write to  RTSI']
        self.fpga_ex_timing = self.session.registers['Use External Timing']
        self.fpga_irq = self.session.registers['Generate IRQ']

        self.loop_timer.write(loop_rate)
        self.fpga_rtsi.write(False)
        self.fpga_ex_timing.write(False)
        self.fpga_irq.write(False)

    def start_fpga_main_loop(self):
        self.fpga_start_control.write(True)

    def stop_fpga(self):
        self.session.reset()
        self.session.close()


    def set_channel(self, channel_name, value):
        self.channel_value_table[channel_name] = value

    def get_channel(self, channel_name):
        return self.channel_value_table[channel_name]

    def vs_read_fifo(self, timeout):
        if self.read_fifo_object is None:
            raise ConfigError('Session not initialized. Please first call the'
                              ' VeriStandFPGA.init fpga method before reading')
        else:
            read_tup = self.read_fifo_object.read(number_of_elements=self.read_packets, timeout_ms=timeout)
            data = read_tup.data
            for i, u64 in enumerate(data):
                this_packet = self.read_packet_list[i]
                read_vals = this_packet._unpack(u64)
                for key in read_vals:
                    self.channel_value_table[key] = read_vals[key]

    def vs_write_fifo(self, timeout):
        if self.write_fifo_object is None:
            raise ConfigError('Session not initialized. '
                              'Please first call the VeriStandFPGA.init_fpga method before writing')
        else:
            write_list = []
            for current_packet in self.write_packet_list:
                packet_vals = []
                for channel in current_packet:
                    packet_vals.append(self.channel_value_table[channel['name']])
                write_list.append(current_packet._pack(packet_vals))
            self.write_fifo_object.write(data=write_list, timeout_ms=timeout)

    def _create_packet(self, direction, index):
        """

        :param direction:
        :param index:
        :return:
        """
        if index == 1 and direction.lower() == 'read':
            this_packet = FirstReadPacket()
        else:
            this_packet = Packet(self, direction, index)
        return this_packet

    def __del__(self):
        try:
            self.stop_fpga()
        except:
            print('Configuration closed')
        print('FPGA hardware session closed.')
        print('{} configuration closed'.format(self.bitfile))


class Packet(object):
    def __init__(self, config, direction, index):
        """
        Generate an object that defines a packet in a DMA FIFO
        The object will have the following attributes: channel_count, name(0-x), description(0-x), and
        data_type(0-x)
        The packet indexes are 1 to N
        The channel indexes are 0 to N
        The difference in indexing is due to the VeriStand FPGA Config file standard
        :param config: the VeriStand FPGA Config object the packet is a part of
        :param direction: direction of the FIFO. This should be 'read' or 'write'.
        :param index: The index of the packet you wish to define. The value should be an integer of 1 or greater.
        :return: a dictionary with channel count, names, descriptions, and data types.
        """
        self.direction = direction
        self.index = index
        if self.direction.lower() == 'read':
            fifo = config.read_fifo_tag
        elif self.direction.lower() == 'write':
            fifo = config.write_fifo_tag
        else:
            raise BaseException('direction must be either read or write')

        packet_def = {}
        packet_tag = fifo[self.index]
        packet_def['channel_count'] = packet_tag.__len__()
        for cindex, child in enumerate(packet_tag):
            packet_def['data_type{}'.format(cindex)] = child.tag
            for grandchild in child:
                if grandchild.tag == 'Name':
                    packet_def['name{}'.format(cindex)] = grandchild.text
                elif grandchild.tag == 'Scale':
                    packet_def['Scale{}'.format(cindex)] = int(grandchild.text)
                elif grandchild.tag == 'FXPWL':
                    packet_def['FXPWL{}'.format(cindex)] = int(grandchild.text)
                elif grandchild.tag == 'FXPIWL':
                    packet_def['FXPIWL{}'.format(cindex)] = int(grandchild.text)
                elif grandchild.tag == 'PWMPeriod':  # PWM period is measured in ticks of the FPGA clock
                    packet_def['PWM_period{}'.format(cindex)] = int(grandchild.text)
                else:
                    continue
        self.definition = packet_def

    def __iter__(self):
        for i in range(self.definition['channel_count']):
            channel = {}
            channel['name'] = self.definition['name{}'.format(i)]
            channel['data_type'] = self.definition['data_type{}'.format(i)]
            if channel['data_type'] == 'FXPI32':
                channel['FXPWL'] = self.definition['FXPWL{}'.format(i)]
                channel['FXPIWL'] = self.definition['FXPIWL{}'.format(i)]
            elif channel['data_type'] == 'I16':
                channel['Scale'] = self.definition['Scale{}'.format(i)]
            yield channel

    def _unpack(self, data):
        """

        :param data: U64 value that comes out of the DMA_Read
        :return: real_values: dictionary of real_values with channel names as keys and unpacked channels as values
        """
        binstr = '{0:064b}'.format(int(data))
        real_values = {}
        for i in range(self.definition['channel_count']):
            if self.definition['data_type{}'.format(i)] == 'FXPI32':
                chnlunpck = 0
                chnldata = binstr[int(i*32):int((i+1)*32)]
                nopad = chnldata[32 - int(self.definition['FXPWL{}'.format(i)]):int((i + 1) * 32)]
                for index, char in enumerate(nopad):
                    if int(nopad[0]) != 0:
                        if int(char) == 0:
                            char = 1
                        else:
                            char = 0
                    powof = int(self.definition['FXPIWL{}'.format(i)]) - 1 - index
                    bitval = int(char) * 2 ** powof
                    chnlunpck = chnlunpck + bitval
                real_values['{}'.format(self.definition['name{}'.format(i)])] = chnlunpck

            elif self.definition['data_type{}'.format(i)] == 'PWM':
                hitime = int(binstr[:32], 2)
                lowtime = int(binstr[32:], 2)
                dutycycle = (hitime/(hitime+lowtime))*100
                real_values['{}'.format(self.definition['name{}'.format(i)])] = dutycycle

            elif self.definition['data_type{}'.format(i)] == 'Boolean':
                bit = int(binstr[63-i])
                real_values['{}'.format(self.definition['name{}'.format(i)])] = bool(bit)

            elif self.definition['data_type{}'.format(i)] == 'I16':
                analog_data_str = binstr[int((3-i)*16):int((4-i)*16)]
                analog_int = 0
                if analog_data_str[0] == '1':
                    for char in range(15):
                        if analog_data_str[char+1] == '0':
                            analog_int += 2**(14-char)
                        elif analog_data_str[char+1] != '1':
                            raise PacketError(message='{} has a non binary character in data string'.format(
                                self.definition['name{}'.format(i)]), packetID=self.index)
                    analog_int *= -1
                    analog_int -= 1
                elif analog_data_str[0] == '0':
                    for char in range(15):
                        if analog_data_str[char+1] == '1':
                            analog_int += 2**(14-char)
                        elif analog_data_str[char+1] == '0':
                            continue
                        else:
                            raise PacketError(message='{} has a non binary character in data string'.format(
                                self.definition['name{}'.format(i)]), packetID=self.index)
                else:
                    raise PacketError(message='{} has a non binary character in data string'.format(
                        self.definition['name{}'.format(i)]), packetID=self.index)
                analog_cal = 0
                scale = self.definition['Scale{}'.format(i)]
                if analog_int > 0:
                    analog_cal = (scale * analog_int)/32767
                elif analog_int < 0:
                    analog_cal = (-1 * scale * analog_int)/-32768
                real_values['{}'.format(self.definition['name{}'.format(i)])] = analog_cal

            else:
                raise PacketError(message='{} has an unsupported data type of {}'.format(
                    self.definition['name{}'.format(i)], self.definition['data_type{}'.format(i)]), packetID=self.index)

        return real_values

    def _pack(self, real_values):
        """

        :param real_values: list of values to write to the channels in this packet
        :return packed_data: a U64 that represents the real values entered into this function
        """
        datastr = ''
        for i in range(self.definition['channel_count']):
            if self.definition['data_type{}'.format(i)] == 'Boolean':
                value = int(real_values[i])
                if value:
                    bit = 1
                else:
                    bit = 0
                datastr = (str(bit)) + datastr

            elif self.definition['data_type{}'.format(i)] == 'PWM':
                dutycycle = int(real_values[0])
                hi_time = int(round((dutycycle/100) * self.definition['PWM_period{}'.format(i)]))
                low_time = self.definition['PWM_period{}'.format(i)] - hi_time
                datastr = '{0:032b}'.format(hi_time) + '{0:032b}'.format(low_time)

            elif self.definition['data_type{}'.format(i)] == 'FXPI32':
                binstr = '0'
                negstr = ''
                value = float(real_values[i])
                for j in range(int(self.definition['FXPWL{}'.format(i)])-1):
                    check = abs(value) - 2**(int(self.definition['FXPIWL{}'.format(i)])-2-j)
                    if check >= 0:
                        binstr = binstr + '1'
                        value = check
                    else:
                        binstr = binstr + '0'
                if int(real_values[i]) < 0:
                    for char in datastr:
                        if char == '0':
                            negstr = negstr + '1'
                        else:
                            negstr = negstr + '0'
                    binstr = negstr
                for j in range(32-int(self.definition['FXPWL{}'.format(i)])):
                    binstr = '0' + binstr
                datastr = binstr + datastr

            elif self.definition['data_type{}'.format(i)] == 'I16':
                calibrated_value = float(real_values[i])
                raw_value = 0
                if calibrated_value > 0:
                    raw_value = int(round((32767 * calibrated_value)/10))
                elif calibrated_value < 0:
                    raw_value = int(round((-32768 * calibrated_value)/-10))
                if raw_value >= 0:
                    binstr = '0'
                    for bit in range(15):
                        bitcheck = int(raw_value - 2 ** (14-bit))
                        if bitcheck >= 0:
                            binstr += '1'
                            raw_value = bitcheck
                        else:
                            binstr += '0'
                else:
                    binstr = '1'
                    for bit in range(15):
                        bitcheck = int(raw_value + 2 ** (14-bit))
                        if bitcheck < 0:
                            binstr += '0'
                            raw_value = bitcheck
                        else:
                            binstr += '1'
                datastr = binstr + datastr

            else:
                raise PacketError(message='{} has an unsupported data type of {}'.format(
                    self.definition['name{}'.format(i)], self.definition['data_type{}'.format(i)]), packetID=self.index)
        packed_data = int(datastr, 2)
        return packed_data

class FirstReadPacket(Packet):
    """

    First Packet of the read FIFO is a nonstandard Boolean. This subclass accounts for that.
    """

    def __init__(self):
        self.definition = {}
        self.definition['channel_count'] = 1
        self.definition['name0'] = 'Is Late?'
        self.definition['data_type0'] = 'Boolean'

