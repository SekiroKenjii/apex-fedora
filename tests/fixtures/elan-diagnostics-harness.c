/* Invalid buffer pointers make accidental non-status reads fail the test. */
#include <gio/gio.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

#define FPI_USB_ENDPOINT_IN 0x80
#define ELAN_EP_CMD_IN 0x83
#define FP_DEVICE_ERROR (g_quark_from_static_string("fp-device-error"))
#define G_USB_DEVICE_ERROR (g_quark_from_static_string("g-usb-device-error"))
static const int pre_scan_cmd = 1, get_image_cmd = 2, other_cmd = 3;
typedef struct { int state; } FpiSsm;
typedef struct {
  const int *cmd;
  unsigned vid, pid;
  gssize apex_read_length;
  int apex_prescan_status;
  guint apex_diag_events;
} FpDevice;
typedef FpDevice FpiDeviceElan;
typedef struct {
  FpiSsm *ssm;
  unsigned endpoint;
  gssize length, actual_length;
  unsigned char *buffer;
} FpiUsbTransfer;
#define FPI_DEVICE_ELAN(x) (x)
static FpDevice *fpi_device_get_usb_device(FpDevice *d) { return d; }
static unsigned g_usb_device_get_vid(FpDevice *d) { return d->vid; }
static unsigned g_usb_device_get_pid(FpDevice *d) { return d->pid; }
static int fpi_device_get_current_action(FpDevice *d) { return 3; }
static int fpi_ssm_get_cur_state(FpiSsm *s) { return s->state; }

/* APEX_DIAGNOSTIC_HELPERS */

static void record(const gchar *domain, GLogLevelFlags level, const gchar *message, gpointer data) {
  g_string_append(data, message); g_string_append_c(data, '\n');
}

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  const char *test = argv[1];
  g_unsetenv("FP_DEBUG_TRANSFER"); g_unsetenv("G_MESSAGES_DEBUG");
  g_setenv("APEX_ELAN_STATUS_DIAGNOSTICS", "1", TRUE);
  FpDevice dev = {.vid = 0x04f3, .pid = 0x0c6e, .cmd = &pre_scan_cmd,
                  .apex_read_length = -1, .apex_prescan_status = -1};
  FpiSsm ssm = {.state = 2};
  FpiUsbTransfer transfer = {.ssm = &ssm, .endpoint = ELAN_EP_CMD_IN,
    .length = 1, .actual_length = 1, .buffer = (void *)(uintptr_t)1};
  unsigned char status = 0xff;
  GError *error = NULL;
  if (g_str_has_prefix(test, "status-")) { status = atoi(test + 7); transfer.buffer = &status; }
  if (!strcmp(test, "disabled")) g_unsetenv("APEX_ELAN_STATUS_DIAGNOSTICS");
  if (!strcmp(test, "wrong-opt-in")) g_setenv("APEX_ELAN_STATUS_DIAGNOSTICS", "yes", TRUE);
  if (!strcmp(test, "debug-transfer")) g_setenv("FP_DEBUG_TRANSFER", "", TRUE);
  if (!strcmp(test, "debug-messages")) g_setenv("G_MESSAGES_DEBUG", "all", TRUE);
  if (!strcmp(test, "wrong-device")) dev.pid = 0x0c58;
  if (!strcmp(test, "wrong-vendor")) dev.vid = 0x1234;
  if (!strcmp(test, "image")) { dev.cmd = &get_image_cmd; transfer.endpoint = 0x82; transfer.length = transfer.actual_length = 8192; }
  if (!strcmp(test, "other-command")) dev.cmd = &other_cmd;
  if (!strcmp(test, "wrong-endpoint")) transfer.endpoint = 0x82;
  if (!strcmp(test, "outgoing")) transfer.endpoint = 0x01;
  if (!strcmp(test, "zero")) transfer.actual_length = 0;
  if (!strcmp(test, "overlong")) transfer.actual_length = 2;
  if (!strcmp(test, "wrong-expected")) transfer.length = 2;
  if (!strcmp(test, "null-buffer")) transfer.buffer = NULL;
  if (!strcmp(test, "failed") || !strcmp(test, "budget"))
    error = g_error_new_literal(G_USB_DEVICE_ERROR, 2, "PRIVATE_PAYLOAD_SENTINEL");
  if (!strcmp(test, "failed")) transfer.actual_length = -1;
  GString *messages = g_string_new("");
  g_log_set_handler(NULL, G_LOG_LEVEL_MESSAGE, record, messages);
  int repeats = !strcmp(test, "budget") ? 20 : 1;
  for (int i = 0; i < repeats; i++) {
    apex_elan_trace_transfer(&transfer, &dev, error);
    if (!error) apex_elan_emit(&dev, &ssm, "probe", transfer.length,
                             dev.apex_read_length, dev.apex_prescan_status, NULL);
  }
  printf("%s", messages->str);
  g_string_free(messages, TRUE); g_clear_error(&error);
  return 0;
}
