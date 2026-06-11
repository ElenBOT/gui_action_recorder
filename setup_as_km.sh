#!/bin/bash
modprobe libcomposite
GADGET="/sys/kernel/config/usb_gadget/my_gadget"

echo "Step 1: Cleaning up old configurations..."
if [ -d "$GADGET" ]; then
    echo "" > "$GADGET/UDC" 2>/dev/null
    rm -f "$GADGET/configs/c.1/hid.usb0"
    rm -f "$GADGET/configs/c.1/hid.usb1"
    rmdir "$GADGET/configs/c.1/strings/0x409" 2>/dev/null
    rmdir "$GADGET/configs/c.1" 2>/dev/null
    rmdir "$GADGET/functions/hid.usb0" 2>/dev/null
    rmdir "$GADGET/functions/hid.usb1" 2>/dev/null
    rmdir "$GADGET/strings/0x409" 2>/dev/null
    rmdir "$GADGET" 2>/dev/null
fi

echo "Step 2: Creating new USB Gadget (Combo KM)..."
mkdir -p "$GADGET"
cd "$GADGET"

echo 0x046d > idVendor
echo 0xc52b > idProduct
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

mkdir -p strings/0x409
echo "123456789" > strings/0x409/serialnumber
echo "Logitech" > strings/0x409/manufacturer
echo "USB Receiver" > strings/0x409/product

mkdir -p configs/c.1/strings/0x409
echo "Config 1" > configs/c.1/strings/0x409/configuration
echo 250 > configs/c.1/MaxPower

echo "Step 3: Setting up Keyboard interface (hid.usb0)..."
mkdir -p functions/hid.usb0
echo 1 > functions/hid.usb0/protocol
echo 1 > functions/hid.usb0/subclass
echo 8 > functions/hid.usb0/report_length
python3 -c "import binascii; open('functions/hid.usb0/report_desc', 'wb').write(binascii.unhexlify('05010906a101050719e029e71500250175019508810295017508810395057501050819012905910295017503910395067508150025650507190029658100c0'))"

echo "Step 4: Setting up Mouse interface (hid.usb1) [ABSOLUTE POINTER]..."
mkdir -p functions/hid.usb1
echo 2 > functions/hid.usb1/protocol
echo 1 > functions/hid.usb1/subclass
echo 5 > functions/hid.usb1/report_length  # Changed from 3 to 5
python3 -c "import binascii; open('functions/hid.usb1/report_desc', 'wb').write(binascii.unhexlify('05010902a1010901a10005091901290315002501950375018102950175058103050109300931150026ff7f350046ff7f751095028102c0c0'))"

echo "Step 5: Binding both interfaces to UDC..."
ln -s functions/hid.usb0 configs/c.1/
ln -s functions/hid.usb1 configs/c.1/
ls /sys/class/udc > UDC

# Handle permissions for /dev/hidg0 and /dev/hidg1
chmod 666 /dev/hidg0 /dev/hidg1

echo "Success: Keyboard + Mouse Combo configuration complete!"
