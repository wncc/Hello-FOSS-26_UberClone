import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { RideMap } from '@/components/RideMap';
import { Body, Button, ErrorText, Row, Sheet, colors, space } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { VEHICLE_ICON, VEHICLE_LABEL, VEHICLE_ORDER, formatDistance, formatDuration, formatFare, shortAddress } from '@/lib/format';
import { DEFAULT_CENTER, addressLabel, useCurrentPosition } from '@/lib/location';
import { useSession } from '@/lib/session';
import type {
  EstimateOption, LatLng, Place, PlaceSearchResult, VehicleType,
} from '@/lib/types';

type Step = 'pickup' | 'drop' | 'choose';
const SHEET_HEIGHT = 300;
const CHOOSE_SHEET_HEIGHT = 440;   // three fare options + the book button

export default function RiderHome() {
  const { api, user, signOut } = useSession();
  const { position, error: locationError, retry: retryLocation } = useCurrentPosition();
  const [step, setStep] = useState<Step>('pickup');
  const [center, setCenter] = useState<LatLng>(DEFAULT_CENTER);
  const [manualRecenter, setManualRecenter] = useState<{ to: LatLng | null; n: number }>({ to: null, n: 0 });
  const recenterTo = manualRecenter.to ?? (step === 'pickup' ? position : null);
  const setRecenterTo = (to: LatLng | null) => setManualRecenter((m) => ({ to, n: m.n + 1 }));
  const [label, setLabel] = useState<string | null>(null);
  const [pickup, setPickup] = useState<Place | null>(null);
  const [drop, setDrop] = useState<Place | null>(null);
  const [options, setOptions] = useState<EstimateOption[]>([]);
  const [selected, setSelected] = useState<VehicleType | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const labelRequest = useRef(0);
  const selectedPlaceLabel = useRef<LatLng | null>(null);
  const [searchText, setSearchText] = useState('');
  const [suggestions, setSuggestions] = useState<PlaceSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [recentPlaces, setRecentPlaces] = useState<PlaceSearchResult[]>([]);
  const searchRequest = useRef(0);
  // Resume an ongoing ride (e.g. app restarted mid-trip).
  useFocusEffect(useCallback(() => {
    api.activeRide().then((ride) => ride && router.replace(`/rider/ride/${ride.id}`)).catch(() => {});
  }, [api]));

  // Address label for the pin, debounced while the map moves.
  useEffect(() => {
    if (step === 'choose') return;
    const id = ++labelRequest.current;
    const t = setTimeout(async () => {
     if (
  selectedPlaceLabel.current?.lat === center.lat &&
  selectedPlaceLabel.current?.lng === center.lng
) {
  return;
}

const text = await addressLabel(center);
if (id === labelRequest.current) setLabel(text);
    }, 500);
    return () => clearTimeout(t);
  }, [center, step]);

  
useEffect(() => {
  const query = searchText.trim();
  const requestId = ++searchRequest.current;

  if (step === 'choose' || query.length < 2) {
    setSuggestions([]);
    setSearching(false);
    setSearchError(null);
    return;
  }

  const timer = setTimeout(async () => {
    setSearching(true);
    setSearchError(null);

    try {
      const results = await api.searchPlaces(query, center);
      if (requestId === searchRequest.current) {
        setSuggestions(results);
      }
    } catch {
      if (requestId === searchRequest.current) {
        setSuggestions([]);
        setSearchError(
          'Place search is unavailable. You can still move the map pin.',
        );
      }
    } finally {
      if (requestId === searchRequest.current) {
        setSearching(false);
      }
    }
  }, 300);

  return () => clearTimeout(timer);
}, [api, searchText, center, step]);


  const here: Place = { lat: center.lat, lng: center.lng, address: label };

  
function selectPlace(place: PlaceSearchResult) {
  const selectedPlace: Place = {
    lat: place.lat,
    lng: place.lng,
    address: place.address,
  };


  selectedPlaceLabel.current = { lat: place.lat, lng: place.lng };
  labelRequest.current += 1;

  setCenter({ lat: place.lat, lng: place.lng });
  setLabel(place.address);
  setSearchText(place.name);
  setSuggestions([]);
  setSearchError(null);
  setRecenterTo({ lat: place.lat, lng: place.lng });

  setRecentPlaces((previous) => [
    place,
    ...previous.filter(
      (recent) =>
        recent.lat !== place.lat || recent.lng !== place.lng,
    ),
  ].slice(0, 5));

  if (step === 'pickup') {
    setPickup(selectedPlace);
  } else if (step === 'drop') {
    setDrop(selectedPlace);
  }
}


  async function confirmPickup() {
    setPickup(here);
    setStep('drop');
    setRecenterTo({ lat: center.lat - 0.01, lng: center.lng + 0.01 });   // nudge so the drop pin starts elsewhere
  }

  async function confirmDrop() {
    if (!pickup) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.estimate(pickup, here);
      const sorted = [...res.options].sort((a, b) => VEHICLE_ORDER.indexOf(a.vehicle_type) - VEHICLE_ORDER.indexOf(b.vehicle_type));
      setDrop(here);
      setOptions(sorted);
      setSelected(sorted.find((o) => o.drivers_nearby > 0)?.vehicle_type ?? sorted[0]?.vehicle_type ?? null);
      setStep('choose');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not get prices');
    } finally {
      setBusy(false);
    }
  }

  async function book() {
    if (!pickup || !drop || !selected) return;
    setBusy(true);
    setError(null);
    try {
      const ride = await api.book(pickup, drop, selected);
      router.replace(`/rider/ride/${ride.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not book the ride');
      setBusy(false);
    }
  }

  function back() {
    setError(null);
    if (step === 'choose') {
      setStep('drop');
      setRecenterTo(drop);
    } else if (step === 'drop') {
      setStep('pickup');
      setRecenterTo(pickup);
    }
  }

  return (
    <View style={{ flex: 1 }}>
      <RideMap
        initialCenter={DEFAULT_CENTER}
        recenterTo={recenterTo}
        recenterKey={manualRecenter.n}
        me={position}
        onCenterChange={step === 'choose' ? undefined : setCenter}
        pinLabel={step === 'pickup' ? 'Pickup' : 'Drop'}
        pickup={step === 'pickup' ? null : pickup}
        drop={step === 'choose' ? drop : null}
        route={step === 'choose' ? options.find((o) => o.vehicle_type === selected)?.route : null}
        bottomInset={step === 'choose' ? CHOOSE_SHEET_HEIGHT : SHEET_HEIGHT}
      />
      <SafeAreaView edges={['top']} style={styles.topBar} pointerEvents="box-none">
        <Row style={{ justifyContent: 'space-between' }}>
          {step !== 'pickup' ? <Chip text="‹ Back" onPress={back} /> : <Chip text={`Hi, ${user?.name?.split(' ')[0] ?? ''}`} />}
          <Row>
            <Chip text="Rides" onPress={() => router.push('/rider/history')} />
            <Chip text="Log out" onPress={signOut} />
          </Row>
        </Row>
      </SafeAreaView>

      <Sheet>
        {step === 'choose' ? (
          <>
            <Body muted numberOfLines={1}>{shortAddress(pickup!.lat, pickup!.lng, pickup!.address)} → {shortAddress(drop!.lat, drop!.lng, drop!.address)}</Body>
            {options.map((o) => (
              <Pressable key={o.vehicle_type} onPress={() => setSelected(o.vehicle_type)}
                         style={[styles.option, selected === o.vehicle_type && styles.optionSelected]}>
                <Text style={{ fontSize: 28 }}>{VEHICLE_ICON[o.vehicle_type]}</Text>
                <View style={{ flex: 1 }}>
                  <Text style={styles.optionTitle}>{VEHICLE_LABEL[o.vehicle_type]}</Text>
                  <Text style={styles.optionSub}>
                    {formatDuration(o.duration_s)} · {formatDistance(o.distance_m)} · {o.drivers_nearby ? `${o.drivers_nearby} nearby` : 'none nearby'}
                  </Text>
                </View>
                <Text style={styles.optionTitle}>{formatFare(o.fare_paise)}</Text>
              </Pressable>
            ))}
            <ErrorText message={error} />
            <Button title={selected ? `Book ${VEHICLE_LABEL[selected]} · Cash` : 'Choose a ride'} onPress={book}
                    loading={busy} disabled={!selected} />
          </>
        ) : (
          <>
            <Text style={styles.optionSub}>{step === 'pickup' ? 'PICKUP' : 'DROP'}</Text>
            
            <View style={styles.searchContainer}>
              <TextInput
                value={searchText}
                onChangeText={setSearchText}
                placeholder={`Search ${step === 'pickup' ? 'pickup' : 'drop'} place`}
                placeholderTextColor={colors.muted}
                style={styles.searchInput}
                accessibilityLabel={`Search ${step} place`}
                returnKeyType="search"
              />

              {searching ? (
                <Text style={styles.searchMessage}>Searching places...</Text>
              ) : null}

              {searchError ? (
                <Text style={styles.searchError}>{searchError}</Text>
              ) : null}

              {!searching && !searchError && searchText.trim().length >= 2 &&
              suggestions.length === 0 ? (
                <Text style={styles.searchMessage}>No matching places found.</Text>
              ) : null}

              {suggestions.map((place, index) => (
                <Pressable
                  key={`${place.lat},${place.lng},${index}`}
                  onPress={() => selectPlace(place)}
                  style={styles.suggestion}
                >
                  <Text style={styles.suggestionName}>{place.name}</Text>
                  <Text style={styles.suggestionAddress}>{place.address}</Text>
                </Pressable>
              ))}

              {recentPlaces.length > 0 ? (
                <>
                  <Text style={styles.recentHeading}>Recent places</Text>
                  {recentPlaces.map((place, index) => (
                    <Pressable
                      key={`recent-${place.lat},${place.lng},${index}`}
                      onPress={() => selectPlace(place)}
                      style={styles.suggestion}
                    >
                      <Text style={styles.suggestionName}>{place.name}</Text>
                      <Text style={styles.suggestionAddress}>{place.address}</Text>
                    </Pressable>
                  ))}
                </>
              ) : null}
            </View>

            <Body numberOfLines={2}>
            {shortAddress(center.lat, center.lng, label)}
            
            </Body>
            <Body muted>Move the map to place the pin.</Body>
            {step === 'pickup' && locationError ? (
              <Row style={{ justifyContent: 'space-between' }}>
                <View style={{ flex: 1 }}><ErrorText message={locationError} /></View>
                <Button title="Retry" kind="secondary" onPress={retryLocation} />
              </Row>
            ) : null}
            <ErrorText message={error} />
            <Button title={step === 'pickup' ? 'Confirm pickup' : 'Confirm drop'}
                    onPress={step === 'pickup' ? confirmPickup : confirmDrop} loading={busy} />
            {step === 'pickup' && position ? <Button title="Use my location" kind="secondary" onPress={() => setRecenterTo({ ...position })} /> : null}
          </>
        )}
      </Sheet>
    </View>
  );
}

function Chip({ text, onPress }: { text: string; onPress?: () => void }) {
  return (
    <Pressable onPress={onPress} disabled={!onPress} style={styles.chip}>
      <Text style={{ fontWeight: '600', color: colors.text }}>{text}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  topBar: { position: 'absolute', top: 0, left: 0, right: 0, paddingHorizontal: space.md, paddingTop: space.sm },
  chip: {
    backgroundColor: colors.bg, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 20,
    shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 6, elevation: 4,
  },
  option: {
    flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.sm, borderRadius: 12,
    borderWidth: 2, borderColor: 'transparent',
  },
  optionSelected: { borderColor: colors.primary, backgroundColor: colors.surface },
  optionTitle: { fontSize: 17, fontWeight: '600', color: colors.text },
  optionSub: { fontSize: 13, color: colors.muted },
  
  searchContainer: {
    gap: 6,
  },
  searchInput: {
    backgroundColor: colors.surface,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.muted,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
  },
  searchMessage: {
    color: colors.muted,
    fontSize: 13,
    paddingVertical: 4,
  },
  searchError: {
    color: '#b42318',
    fontSize: 13,
    paddingVertical: 4,
  },
  suggestion: {
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: colors.surface,
  },
  suggestionName: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '600',
  },
  suggestionAddress: {
    color: colors.muted,
    fontSize: 12,
  },
  recentHeading: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: '600',
    marginTop: 4,
  },


});
