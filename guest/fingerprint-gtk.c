/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Compile the complete dialog, including its template and asynchronous callbacks. */
#include "cc-fingerprint-dialog.c"
#include <act/act-user-manager.h>

static GDBusConnection *control;

static void
pump (guint milliseconds)
{
  gint64 end = g_get_monotonic_time () + milliseconds * 1000;
  do {
    while (g_main_context_iteration (NULL, FALSE));
    g_usleep (1000);
  } while (g_get_monotonic_time () < end);
}

#define WAIT(condition) G_STMT_START { \
  gint64 deadline = g_get_monotonic_time () + 8 * G_TIME_SPAN_SECOND; \
  while (!(condition) && g_get_monotonic_time () < deadline) pump (10); \
  g_assert_true (condition); \
} G_STMT_END

static GVariant *
command (const char *method, GVariant *parameters)
{
  GError *error = NULL;
  GVariant *result = g_dbus_connection_call_sync (control, "org.apex.FingerprintTest",
      "/org/apex/FingerprintTest", "org.apex.FingerprintTest", method,
      parameters, NULL, G_DBUS_CALL_FLAGS_NONE, 3000, NULL, &error);
  g_assert_no_error (error);
  return result;
}

static guint
count (const char *method)
{
  g_autoptr(GVariant) result = command ("Count", g_variant_new ("(s)", method));
  guint value;
  g_variant_get (result, "(u)", &value);
  return value;
}

static void
start (CcFingerprintDialog *dialog)
{
  guint before = count ("EnrollStart");
  GtkWidget *button = gtk_widget_get_first_child (GTK_WIDGET (dialog->add_print_popover_box));
  g_assert_true (GTK_IS_BUTTON (button));
  g_signal_emit_by_name (button, "clicked");
  WAIT (count ("EnrollStart") == before + 1);
  WAIT (!(dialog->dialog_state & DIALOG_STATE_DEVICE_ENROLL_STARTING));
  g_assert_true (dialog->dialog_state & DIALOG_STATE_DEVICE_ENROLLING);
}

static void
fail_enroll (CcFingerprintDialog *dialog)
{
  g_autoptr(GVariant) result = command ("Status", g_variant_new ("(s)", "enroll-disconnected"));
  WAIT (g_strcmp0 (gtk_label_get_text (dialog->enroll_result_message),
                  "Fingerprint device disconnected") == 0);
}

static CcFingerprintDialog *
open_dialog (CcFingerprintManager *manager, GtkWindow *window)
{
  CcFingerprintDialog *dialog = cc_fingerprint_dialog_new (manager);
  g_object_ref_sink (dialog);
  adw_dialog_present (ADW_DIALOG (dialog), GTK_WIDGET (window));
  WAIT (dialog->dialog_state == DIALOG_STATE_DEVICE_CLAIMED);
  WAIT (gtk_widget_get_mapped (GTK_WIDGET (dialog)));
  return dialog;
}

int
main (int argc, char **argv)
{
  g_assert_cmpint (argc, ==, 2);
  const char *scenario = argv[1];
  /* Criticals and memory errors must fail even when no assertion catches them. */
  g_log_set_always_fatal (G_LOG_LEVEL_ERROR | G_LOG_LEVEL_CRITICAL);
  adw_init ();
  control = g_bus_get_sync (G_BUS_TYPE_SYSTEM, NULL, NULL);
  g_assert_nonnull (control);
  ActUserManager *users = act_user_manager_get_default ();
  ActUser *user = act_user_manager_get_user (users, "builder");
  WAIT (act_user_is_loaded (user));
  g_assert_cmpstr (act_user_get_user_name (user), ==, "builder");
  g_assert_cmpuint (act_user_get_uid (user), ==, getuid ());
  CcFingerprintManager *manager = cc_fingerprint_manager_new (user);
  WAIT (cc_fingerprint_manager_get_state (manager) != CC_FINGERPRINT_STATE_UPDATING);
  GtkWindow *window = GTK_WINDOW (adw_window_new ());
  gtk_window_set_default_size (window, 700, 600);
  gtk_window_present (window);
  CcFingerprintDialog *dialog = open_dialog (manager, window);
  start (dialog);
  g_print ("READY %s\n", scenario);

  if (g_str_equal (scenario, "daemon-replace")) {
    g_autoptr(GVariant) result = command ("Replace", NULL);
    pump (1200);
    /* Loss must not leave an in-flight Claim. A new dialog must use the new owner. */
    WAIT (!(dialog->dialog_state & DIALOG_STATE_DEVICE_CLAIMING));
  } else {
    if (!g_str_equal (scenario, "cancel-twice"))
      fail_enroll (dialog);
    if (!g_str_equal (scenario, "error-close")) {
      gboolean pending = g_str_equal (scenario, "cancel-twice") ||
                         g_str_equal (scenario, "close-pending");
      if (pending) {
        g_autoptr(GVariant) result = command ("DelayStop", g_variant_new ("(u)", 400));
      }
      g_signal_emit_by_name (dialog->cancel_button, "clicked");
      if (g_str_equal (scenario, "cancel-twice"))
        g_signal_emit_by_name (dialog->cancel_button, "clicked");
      if (!g_str_equal (scenario, "close-pending")) {
        WAIT (dialog->dialog_state == DIALOG_STATE_DEVICE_CLAIMED);
        g_assert_cmpuint (count ("EnrollStop"), ==, 1);
        g_assert_cmpuint (count ("Claim"), ==, 1);
        start (dialog);
      }
    }
  }

  guint releases = count ("Release");
  adw_dialog_close (ADW_DIALOG (dialog));
  /* Drain callbacks while the real window/dialog ownership changes. */
  g_object_unref (dialog);
  pump (1200);
  if (!g_str_equal (scenario, "daemon-replace"))
    g_assert_cmpuint (count ("Release"), ==, releases + 1);
  CcFingerprintDialog *again = open_dialog (manager, window);
  start (again);
  adw_dialog_close (ADW_DIALOG (again));
  g_object_unref (again);
  pump (700);
  g_assert_cmpuint (count ("AlreadyInUse"), ==, 0);
  g_assert_cmpuint (count ("Owners"), ==, 0);
  gtk_window_destroy (window);
  g_object_unref (manager);
  g_object_unref (control);
  g_print ("PASS %s\n", scenario);
  return 0;
}
