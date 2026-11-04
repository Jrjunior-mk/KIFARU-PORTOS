from kifaru_gateway import vms


def test_modbus_crc_check_value():
    assert vms.crc16_modbus(b"123456789") == 0x4B37
    # classic example: 01 03 00 00 00 0A -> CRC C5 CD
    assert vms.req_read_holding(1, 0, 10) == bytes.fromhex("010300000000a") if False else vms.req_read_holding(1, 0, 10)[-2:] == bytes.fromhex("c5cd")


def test_decision_mapping_writes_registers_and_text():
    be = vms.MockModbusBackend()
    ctl = vms.VmsController(be)
    st = ctl.show("AMBER", plate="KCA 123A")
    assert st["signal"] == "AMBER" and st["message"] == "WEIGHBRIDGE ->" and not st["fault"]
    status = ctl.read_status()
    assert status["signal_state"] == vms.SIGNAL["AMBER"] and status["message_id"] == vms.MESSAGE_ID["WEIGHBRIDGE ->"] and status["plate_enable"] == 1
    text = b"".join(be.holding[1][vms.REG_CUSTOM_TEXT + i].to_bytes(2, "big") for i in range(32)).decode().strip()
    assert text == "KCA 123A WEIGHBRIDGE ->"
    assert be.holding[2][vms.REG_SIGNAL_STATE] == vms.SIGNAL["AMBER"]
    ctl.show("GREEN")
    assert ctl.read_status()["signal_state"] == 1 and ctl.read_status()["plate_enable"] == 0
    ctl.show("RED", plate="KDB 456B")
    assert ctl.read_status()["message_id"] == 3


def test_vms_fault_is_reported_not_raised():
    be = vms.MockModbusBackend(fail_next=1)
    ctl = vms.VmsController(be)
    st = ctl.show("GREEN")
    assert st["fault"] is True and "no response" in st["error"]
    assert ctl.heartbeat() is True and ctl.state["fault"] is False
