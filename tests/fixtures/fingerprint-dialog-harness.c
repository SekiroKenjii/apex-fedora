/* Test shims for extracted GNOME handlers. No GTK, D-Bus or device operations. */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <float.h>
#include <math.h>

typedef bool gboolean;
typedef unsigned guint;
typedef double gdouble;
typedef void *gpointer;
typedef struct {
  unsigned dialog_state, enroll_stage_passed_id, enroll_stages_passed;
  double enroll_progress;
  void *device, *cancel_button, *done_button, *enrollment_view;
  void *manager, *cancellable, *enrolled_fingers, *stack, *prints_manager;
} CcFingerprintDialog;
typedef CcFingerprintDialog AdwDialog;
#define TRUE true
#define FALSE false
#define DIALOG_STATE_DEVICE_CLAIMED 1u
#define DIALOG_STATE_DEVICE_ENROLLING 2u
#define CC_FINGERPRINT_DIALOG(x) ((CcFingerprintDialog *)(x))
#define GTK_WIDGET(x) (x)
#define ADW_DIALOG(x) (x)
#define C_(context, message) (message)
#define _(message) (message)
#define MIN(a,b) ((a) < (b) ? (a) : (b))
#define G_APPROX_VALUE(a,b,e) (fabs((a)-(b)) <= (e))
#define g_return_if_fail(test) do { if (!(test)) return; } while (0)
#define g_debug(...) ((void)0)
#define g_warning(...) ((void)0)
#define g_clear_handle_id(id, fn) (*(id) = 0)
#define g_clear_object(ptr) (*(ptr) = NULL)
#define g_clear_pointer(ptr, fn) (*(ptr) = NULL)
enum { ENROLL_STATE_SUCCESS, ENROLL_STATE_NORMAL, ENROLL_STATE_RETRY,
       ENROLL_STATE_COMPLETED, ENROLL_STATE_WARNING };
static int stop_calls, release_calls, cancel_calls;
static bool g_str_equal(const char *a, const char *b) { return strcmp(a,b) == 0; }
static void remove_dialog_state(CcFingerprintDialog *s, unsigned mask) { s->dialog_state &= ~mask; }
static void set_enroll_result_message(CcFingerprintDialog *s, int state, const char *m) {}
static unsigned cc_fprintd_device_get_num_enroll_stages(void *d) { return 5; }
static const char *cc_fprintd_device_get_name(void *d) { return "fake"; }
static const char *cc_fprintd_device_get_scan_type(void *d) { return "press"; }
static const char *enroll_result_str_to_msg(const char *r, bool swipe) { return r; }
static bool stage_passed_timeout_cb(void *s) { return false; }
static unsigned g_timeout_add(int ms, bool (*cb)(void *), void *s) { return 1; }
static void gtk_widget_set_sensitive(void *widget, bool value) {}
static void gtk_widget_grab_focus(void *widget) {}
static void gtk_stack_set_visible_child(void *stack, void *child) {}
static void cc_fingerprint_manager_update_state(void *m, void *a, void *b) {}
static void disconnect_device_signals(CcFingerprintDialog *s) {}
static void cc_fprintd_device_call_enroll_stop_sync(void *d, void *a, void *b) { stop_calls++; }
static void cc_fprintd_device_call_release(void *d, void *a, void *b, void *c) { release_calls++; }
static void g_cancellable_cancel(void *c) {}
static void *g_cancellable_new(void) { return NULL; }
static void g_set_object(void **out, void *value) { *out = value; }
static void enroll_stop(CcFingerprintDialog *s) { cancel_calls++; }
static void adw_dialog_set_can_close(void *d, bool value) {}
static void adw_dialog_close(void *d) {}

/* A checked source reader inserts the unmodified upstream function bodies here. */
/* APEX_EXTRACTED_HANDLERS */

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  CcFingerprintDialog dialog = {.dialog_state = 3, .device = (void *)1};
  const char *result = "enroll-disconnected";
  bool done = true;
  if (!strcmp(argv[1], "retry")) { result = "enroll-retry-scan"; done = false; }
  if (!strcmp(argv[1], "complete")) result = "enroll-completed";
  if (!strcmp(argv[1], "unknown-error")) result = "enroll-unknown-error";
  if (!strcmp(argv[1], "unclaimed")) dialog.dialog_state = 0;
  else handle_enroll_signal(&dialog, result, done);
  unsigned after = dialog.dialog_state;
  if (!strcmp(argv[1], "cancel")) cancel_button_clicked_cb(&dialog);
  cc_fingerprint_dialog_close_attempt(&dialog);
  printf("{\"state_after_signal\":%u,\"stop_calls\":%d,\"release_calls\":%d,\"cancel_calls\":%d}\n",
         after, stop_calls, release_calls, cancel_calls);
  return 0;
}
