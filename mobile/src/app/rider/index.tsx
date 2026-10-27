import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { LanguagePicker } from "@/components/LanguagePicker";
import { RideMap } from "@/components/RideMap";
import {
  Body,
  Button,
  ErrorText,
  Row,
  Sheet,
  colors,
  space,
} from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import {
  VEHICLE_ICON,
  VEHICLE_ORDER,
  formatDistance,
  formatDuration,
  formatFare,
  shortAddress,
} from "@/lib/format";
import {
  DEFAULT_CENTER,
  addressLabel,
  useCurrentPosition,
} from "@/lib/location";
import { useSession } from "@/lib/session";
import type { EstimateOption, LatLng, Place, VehicleType } from "@/lib/types";

type Step = "pickup" | "drop" | "choose";

const SHEET_HEIGHT = 300;
const CHOOSE_SHEET_HEIGHT = 440;

export default function RiderHome() {
  const { api, user, signOut } = useSession();
  const { t } = useLanguage();
  const {
    position,
    error: locationError,
    retry: retryLocation,
  } = useCurrentPosition();

  const [step, setStep] = useState<Step>("pickup");
  const [center, setCenter] = useState<LatLng>(DEFAULT_CENTER);
  const [manualRecenter, setManualRecenter] = useState<{
    to: LatLng | null;
    n: number;
  }>({
    to: null,
    n: 0,
  });
  const recenterTo = manualRecenter.to ?? (step === "pickup" ? position : null);
  const setRecenterTo = (to: LatLng | null) =>
    setManualRecenter((m) => ({ to, n: m.n + 1 }));

  const [label, setLabel] = useState<string | null>(null);
  const [pickup, setPickup] = useState<Place | null>(null);
  const [drop, setDrop] = useState<Place | null>(null);
  const [options, setOptions] = useState<EstimateOption[]>([]);
  const [selected, setSelected] = useState<VehicleType | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const labelRequest = useRef(0);

  function vehicleName(vehicle: VehicleType) {
    switch (vehicle) {
      case "bike":
        return t("bike");
      case "auto_rickshaw":
        return t("auto");
      case "car":
        return t("cab");
    }
  }

  useFocusEffect(
    useCallback(() => {
      api
        .activeRide()
        .then((ride) => ride && router.replace(`/rider/ride/${ride.id}`))
        .catch(() => {});
    }, [api]),
  );

  useEffect(() => {
    if (step === "choose") return;

    const id = ++labelRequest.current;
    const timeout = setTimeout(async () => {
      const text = await addressLabel(center);
      if (id === labelRequest.current) setLabel(text);
    }, 500);

    return () => clearTimeout(timeout);
  }, [center, step]);

  const here: Place = {
    lat: center.lat,
    lng: center.lng,
    address: label,
  };

  async function confirmPickup() {
    setPickup(here);
    setStep("drop");
    setRecenterTo({ lat: center.lat - 0.01, lng: center.lng + 0.01 });
  }

  async function confirmDrop() {
    if (!pickup) return;

    setBusy(true);
    setError(null);

    try {
      const res = await api.estimate(pickup, here);
      const sorted = [...res.options].sort(
        (a, b) =>
          VEHICLE_ORDER.indexOf(a.vehicle_type) -
          VEHICLE_ORDER.indexOf(b.vehicle_type),
      );

      setDrop(here);
      setOptions(sorted);
      setSelected(
        sorted.find((o) => o.drivers_nearby > 0)?.vehicle_type ??
          sorted[0]?.vehicle_type ??
          null,
      );
      setStep("choose");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("couldNotGetPrices"));
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
      setError(e instanceof ApiError ? e.message : t("couldNotBook"));
      setBusy(false);
    }
  }

  function back() {
    setError(null);

    if (step === "choose") {
      setStep("drop");
      setRecenterTo(drop);
    } else if (step === "drop") {
      setStep("pickup");
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
        onCenterChange={step === "choose" ? undefined : setCenter}
        pinLabel={step === "pickup" ? t("pickup") : t("drop")}
        pickup={step === "pickup" ? null : pickup}
        drop={step === "choose" ? drop : null}
        route={
          step === "choose"
            ? options.find((o) => o.vehicle_type === selected)?.route
            : null
        }
        bottomInset={step === "choose" ? CHOOSE_SHEET_HEIGHT : SHEET_HEIGHT}
      />

      <SafeAreaView
        edges={["top"]}
        style={styles.topBar}
        pointerEvents="box-none"
      >
        <Row style={{ justifyContent: "space-between", alignItems: "center" }}>
          {step !== "pickup" ? (
            <Chip text={`‹ ${t("back")}`} onPress={back} />
          ) : (
            <Chip text={user?.name?.split(" ")[0] ?? ""} />
          )}

          <Row>
            <LanguagePicker />
            <Chip
              text={t("rides")}
              onPress={() => router.push("/rider/history")}
            />
            <Chip text={t("logout")} onPress={signOut} />
          </Row>
        </Row>
      </SafeAreaView>

      <Sheet>
        {step === "choose" ? (
          <>
            <Body muted numberOfLines={1}>
              {shortAddress(pickup!.lat, pickup!.lng, pickup!.address)} →{" "}
              {shortAddress(drop!.lat, drop!.lng, drop!.address)}
            </Body>

            {options.map((o) => (
              <Pressable
                key={o.vehicle_type}
                onPress={() => setSelected(o.vehicle_type)}
                style={[
                  styles.option,
                  selected === o.vehicle_type && styles.optionSelected,
                ]}
              >
                <Text style={{ fontSize: 28 }}>
                  {VEHICLE_ICON[o.vehicle_type]}
                </Text>

                <View style={{ flex: 1 }}>
                  <Text style={styles.optionTitle}>
                    {vehicleName(o.vehicle_type)}
                  </Text>
                  <Text style={styles.optionSub}>
                    {formatDuration(o.duration_s)} ·{" "}
                    {formatDistance(o.distance_m)} ·{" "}
                    {o.drivers_nearby
                      ? `${o.drivers_nearby} ${t("nearby")}`
                      : t("noDriversNearby")}
                  </Text>
                </View>

                <Text style={styles.optionTitle}>
                  {formatFare(o.fare_paise)}
                </Text>
              </Pressable>
            ))}

            <ErrorText message={error} />

            <Button
              title={
                selected
                  ? t("bookRide", {
                      vehicle: vehicleName(selected),
                      payment: t("cash"),
                    })
                  : t("chooseRide")
              }
              onPress={book}
              loading={busy}
              disabled={!selected}
            />
          </>
        ) : (
          <>
            <Text style={styles.optionSub}>
              {step === "pickup" ? t("pickupUpper") : t("dropUpper")}
            </Text>

            <Body numberOfLines={2}>
              {shortAddress(center.lat, center.lng, label)}
            </Body>
            <Body muted>{t("moveMap")}</Body>

            {step === "pickup" && locationError ? (
              <Row style={{ justifyContent: "space-between" }}>
                <View style={{ flex: 1 }}>
                  <ErrorText message={locationError} />
                </View>
                <Button
                  title={t("retry")}
                  kind="secondary"
                  onPress={retryLocation}
                />
              </Row>
            ) : null}

            <ErrorText message={error} />

            <Button
              title={step === "pickup" ? t("confirmPickup") : t("confirmDrop")}
              onPress={step === "pickup" ? confirmPickup : confirmDrop}
              loading={busy}
            />

            {step === "pickup" && position ? (
              <Button
                title={t("useMyLocation")}
                kind="secondary"
                onPress={() => setRecenterTo({ ...position })}
              />
            ) : null}
          </>
        )}
      </Sheet>
    </View>
  );
}

function Chip({ text, onPress }: { text: string; onPress?: () => void }) {
  return (
    <Pressable onPress={onPress} disabled={!onPress} style={styles.chip}>
      <Text style={{ fontWeight: "600", color: colors.text }}>{text}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  topBar: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    paddingHorizontal: space.md,
    paddingTop: space.sm,
  },
  chip: {
    backgroundColor: colors.bg,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    shadowColor: "#000",
    shadowOpacity: 0.12,
    shadowRadius: 6,
    elevation: 4,
  },
  option: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.md,
    padding: space.sm,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: "transparent",
  },
  optionSelected: {
    borderColor: colors.primary,
    backgroundColor: colors.surface,
  },
  optionTitle: {
    fontSize: 17,
    fontWeight: "600",
    color: colors.text,
  },
  optionSub: {
    fontSize: 13,
    color: colors.muted,
  },
});
