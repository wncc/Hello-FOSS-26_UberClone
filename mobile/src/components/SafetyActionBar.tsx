import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  Modal,
  StyleSheet,
  Share,
  Linking,
  Platform,
  ActivityIndicator,
} from 'react-native';
import { useSession } from '@/lib/session';
import type { Ride } from '../lib/types';

interface SafetyActionsProps {
  ride?: Ride | null;
}

export const SafetyActionsBar: React.FC<SafetyActionsProps> = ({ ride }) => {
  // 1. Declare ALL hooks unconditionally at the top
  const { api } = useSession();
  const [sharing, setSharing] = useState(false);
  const [sosModalVisible, setSosModalVisible] = useState(false);
  const [sosSending, setSosSending] = useState(false);

  // 2. Conditional return comes AFTER hooks
  if (!ride) return null;

  const rideId = ride.id;
  const currentLat = ride.pickup?.lat ?? 19.0178;
  const currentLng = ride.pickup?.lng ?? 72.8478;

  const handleShareTrip = async () => {
    if (!rideId) return;
    try {
      setSharing(true);
      const data = await api.shareTrip(rideId);
      const shareMessage = `Track my live UberClone ride here: ${data?.url || ''}`;

      if (Platform.OS === 'web') {
        if (navigator.clipboard && data?.url) {
          await navigator.clipboard.writeText(data.url);
          window.alert(`Tracking link copied to clipboard!\n\n${data.url}`);
        } else {
          window.prompt('Copy your live tracking link:', data?.url || '');
        }
      } else {
        await Share.share({
          message: shareMessage,
          url: data?.url,
          title: 'Track My Ride',
        });
      }
    } catch (err: any) {
      const msg = err?.message || 'Could not generate share link.';
      Platform.OS === 'web' ? window.alert(msg) : alert(msg);
    } finally {
      setSharing(false);
    }
  };

  const confirmAndTriggerSOS = async () => {
    if (!rideId) return;
    setSosSending(true);
    Linking.openURL('tel:112').catch(() => {});

    try {
      await api.triggerSOS(rideId, currentLat, currentLng);
      setSosModalVisible(false);
      const successMsg = 'SOS alert logged with your current coordinates. Emergency services (112) triggered.';
      Platform.OS === 'web' ? window.alert(successMsg) : alert(successMsg);
    } catch (err: any) {
      setSosModalVisible(false);
      const errMsg = 'Emergency dialer opened, but logging SOS to server failed.';
      Platform.OS === 'web' ? window.alert(errMsg) : alert(errMsg);
    } finally {
      setSosSending(false);
    }
  };

  return (
    <View style={styles.container}>
      <TouchableOpacity
        style={styles.shareButton}
        onPress={handleShareTrip}
        disabled={sharing}
      >
        {sharing ? (
          <ActivityIndicator size="small" color="#FFFFFF" />
        ) : (
          <Text style={styles.shareText}>Share Trip</Text>
        )}
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.sosButton}
        onPress={() => setSosModalVisible(true)}
      >
        <Text style={styles.sosText}>SOS</Text>
      </TouchableOpacity>

      <Modal
        visible={sosModalVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setSosModalVisible(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Emergency SOS</Text>
            <Text style={styles.modalBody}>
              This will immediately dial emergency services (112) and log your live GPS location with our safety team.
            </Text>

            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.cancelBtn}
                onPress={() => setSosModalVisible(false)}
                disabled={sosSending}
              >
                <Text style={styles.cancelBtnText}>Cancel</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={styles.confirmSosBtn}
                onPress={confirmAndTriggerSOS}
                disabled={sosSending}
              >
                {sosSending ? (
                  <ActivityIndicator size="small" color="#FFFFFF" />
                ) : (
                  <Text style={styles.confirmSosText}>Call 112</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 12,
  },
  shareButton: {
    flex: 1,
    backgroundColor: '#2563EB',
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  shareText: { color: '#FFFFFF', fontWeight: '600', fontSize: 15 },
  sosButton: {
    backgroundColor: '#DC2626',
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sosText: { color: '#FFFFFF', fontWeight: '700', fontSize: 15 },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.75)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  modalCard: {
    width: '100%',
    maxWidth: 360,
    backgroundColor: '#1E1E1E',
    borderRadius: 14,
    padding: 24,
  },
  modalTitle: { color: '#EF4444', fontSize: 20, fontWeight: '700', marginBottom: 10 },
  modalBody: { color: '#D4D4D8', fontSize: 14, lineHeight: 20, marginBottom: 24 },
  modalActions: { flexDirection: 'row', gap: 12 },
  cancelBtn: {
    flex: 1,
    backgroundColor: '#27272A',
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  cancelBtnText: { color: '#E4E4E7', fontWeight: '600', fontSize: 14 },
  confirmSosBtn: {
    flex: 1.4,
    backgroundColor: '#DC2626',
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  confirmSosText: { color: '#FFFFFF', fontWeight: '700', fontSize: 14 },
});