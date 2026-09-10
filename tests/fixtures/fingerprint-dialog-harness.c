/* Extracted handlers; real GLib cancellation, fake widgets and D-Bus replies. */
#include <gio/gio.h>
#include <assert.h>
#include <stdio.h>
#include <float.h>
#include <math.h>

/* APEX_DIALOG_STATE */
typedef struct {
  unsigned dialog_state, enroll_stage_passed_id, enroll_stages_passed;
  double enroll_progress;
  GObject *device, *manager;
  GCancellable *cancellable;
  char **enrolled_fingers;
  void *cancel_button, *done_button, *enrollment_view, *stack, *prints_manager;
} CcFingerprintDialog;
typedef CcFingerprintDialog AdwDialog;
typedef GObject CcFprintdDevice;
#define CC_FINGERPRINT_DIALOG(x) ((CcFingerprintDialog *)(x))
#define CC_FPRINTD_DEVICE(x) (x)
#define GTK_WIDGET(x) (x)
#define ADW_DIALOG(x) (x)
#define C_(context, message) (message)
#define _(message) (message)
#undef G_DBUS_PROXY
#define G_DBUS_PROXY(x) (x)
#define g_dbus_proxy_get_name_owner fake_name_owner
enum { ENROLL_STATE_SUCCESS, ENROLL_STATE_NORMAL, ENROLL_STATE_RETRY,
       ENROLL_STATE_COMPLETED, ENROLL_STATE_WARNING, ENROLL_STATE_ERROR };
static int stop_calls, release_calls, cancel_calls, claim_calls;
static gboolean owner_present = TRUE, cancelled_callback;
static GAsyncReadyCallback pending;
static GCancellable *pending_cancel;
static GObject *pending_device;
static gpointer pending_self;
static GError *reply_error;
static void remove_dialog_state(CcFingerprintDialog *s, unsigned mask) { s->dialog_state &= ~mask; }
static gboolean add_dialog_state(CcFingerprintDialog *s, unsigned mask) {
  unsigned previous = s->dialog_state; s->dialog_state |= mask;
  return previous != s->dialog_state;
}
typedef struct { CcFingerprintDialog *dialog; unsigned state; } DialogStateRemover;
static DialogStateRemover *auto_state_remover(CcFingerprintDialog *s, unsigned mask) {
  DialogStateRemover *r = g_new0(DialogStateRemover, 1);
  r->dialog = s; r->state = mask; return r;
}
static void free_remover(DialogStateRemover *r) {
  remove_dialog_state(r->dialog, r->state); g_free(r);
}
G_DEFINE_AUTOPTR_CLEANUP_FUNC(DialogStateRemover, free_remover)
static void set_enroll_result_message(CcFingerprintDialog *s, int state, const char *m) {}
static unsigned cc_fprintd_device_get_num_enroll_stages(void *d) { return 5; }
static const char *cc_fprintd_device_get_name(void *d) { return "fake"; }
static const char *cc_fprintd_device_get_scan_type(void *d) { return "press"; }
static const char *enroll_result_str_to_msg(const char *r, gboolean swipe) { return r; }
static gboolean stage_passed_timeout_cb(void *s) { return FALSE; }
static void gtk_widget_set_sensitive(void *widget, gboolean value) {}
static void gtk_widget_grab_focus(void *widget) {}
static void gtk_stack_set_visible_child(void *stack, void *child) {}
static void cc_fingerprint_manager_update_state(void *m, void *a, void *b) {}
static void disconnect_device_signals(CcFingerprintDialog *s) {}
static void cc_fprintd_device_call_enroll_stop_sync(void *d, void *a, void *b) { stop_calls++; }
static void cc_fprintd_device_call_release(void *d, void *a, void *b, void *c) { release_calls++; }
static void adw_dialog_set_can_close(void *d, gboolean value) {}
static void adw_dialog_close(void *d) {}
static char *fake_name_owner(void *d) { return owner_present ? g_strdup(":1.fake") : NULL; }
static void claim_device(CcFingerprintDialog *s) { claim_calls++; add_dialog_state(s, DIALOG_STATE_DEVICE_CLAIMING); }
static void notify_error(CcFingerprintDialog *s, const char *m) {}
static const char *dbus_error_to_human(CcFingerprintDialog *s, GError *e) { return "synthetic stop failure"; }
static void cc_fprintd_device_call_enroll_stop_finish(GObject *d, GAsyncResult *r, GError **e) {
  if (reply_error) *e = g_error_copy(reply_error);
}
static void cc_fprintd_device_call_enroll_stop(GObject *d, GCancellable *c, GAsyncReadyCallback cb, gpointer s) {
  assert(pending == NULL); cancel_calls++;
  pending = cb; pending_cancel = g_object_ref(c); pending_device = g_object_ref(d); pending_self = s;
}
static void dispatch_stop(gboolean fail) {
  assert(pending != NULL);
  cancelled_callback = g_cancellable_is_cancelled(pending_cancel);
  if (cancelled_callback) reply_error = g_error_new_literal(G_IO_ERROR, G_IO_ERROR_CANCELLED, "cancelled");
  else if (fail) reply_error = g_error_new_literal(G_IO_ERROR, G_IO_ERROR_FAILED, "synthetic failure");
  pending(pending_device, NULL, pending_self);
  pending = NULL; g_clear_error(&reply_error);
  g_clear_object(&pending_cancel); g_clear_object(&pending_device);
}

/* APEX_EXTRACTED_HANDLERS */

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  const char *test = argv[1];
  CcFingerprintDialog dialog = {.dialog_state = DIALOG_STATE_IDLE,
    .device = g_object_new(G_TYPE_OBJECT, NULL), .cancellable = g_cancellable_new()};
  const char *result = "enroll-disconnected";
  gboolean done = TRUE;
  /* Repeated Cancel also fails in the ordinary upstream enrollment path. */
  if (!strcmp(test, "retry") || !strcmp(test, "cancel-twice")) { result = "enroll-retry-scan"; done = FALSE; }
  if (!strcmp(test, "complete")) { result = "enroll-completed"; dialog.enroll_stages_passed = 4; }
  if (!strcmp(test, "unknown-error")) result = "enroll-unknown-error";
  if (!strcmp(test, "unclaimed")) dialog.dialog_state = 0;
  else handle_enroll_signal(&dialog, result, done);
  unsigned after = dialog.dialog_state;
  if (!strcmp(test, "daemon-gone") || !strcmp(test, "daemon-present")) {
    owner_present = !strcmp(test, "daemon-present");
    on_device_owner_changed(dialog.device, NULL, &dialog);
  }
  if (!strcmp(test, "cancel") || g_str_has_prefix(test, "stop-") ||
      !strcmp(test, "cancel-twice") || !strcmp(test, "close-pending")) {
    cancel_button_clicked_cb(&dialog);
    if (!strcmp(test, "cancel-twice")) cancel_button_clicked_cb(&dialog);
  }
  unsigned callback_state = dialog.dialog_state;
  if (pending && (g_str_has_prefix(test, "stop-") || !strcmp(test, "cancel-twice"))) {
    dispatch_stop(!strcmp(test, "stop-error")); callback_state = dialog.dialog_state;
  }
  cc_fingerprint_dialog_close_attempt(&dialog);
  if (pending) dispatch_stop(FALSE);
  printf("{\"state_after_signal\":%u,\"state_after_callback\":%u,\"stop_calls\":%d,\"release_calls\":%d,\"cancel_calls\":%d,\"claim_calls\":%d,\"cancelled_callback\":%s}\n",
         after, callback_state, stop_calls, release_calls, cancel_calls, claim_calls, cancelled_callback ? "true" : "false");
  return 0;
}
