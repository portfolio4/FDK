# Basys3 oscillator: 100 MHz.
set_property -dict {PACKAGE_PIN W5 IOSTANDARD LVCMOS33} [get_ports clk]
create_clock -name sys_clk -period 10.000 [get_ports clk]

# Center pushbutton: active-high reset.
set_property -dict {PACKAGE_PIN U18 IOSTANDARD LVCMOS33} [get_ports rst]

# USB UART bridge TX connects to FPGA RX through programming port J4.
set_property -dict {PACKAGE_PIN B18 IOSTANDARD LVCMOS33} [get_ports rx]

# FPGA TX to the USB-UART bridge's RX input.
set_property -dict {PACKAGE_PIN A18 IOSTANDARD LVCMOS33} [get_ports tx]
